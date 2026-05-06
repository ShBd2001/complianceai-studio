"""Tests de la plomberie du planificateur elle-meme (app/services/scheduler.py) :
orchestration du tick, resilience aux exceptions, et le point le plus critique
pour la securite du dispositif — le verrou consultatif Postgres empeche
vraiment deux executions concurrentes du meme tick.
"""

import asyncio
import threading
import time

import pytest

from app.services import scheduler as scheduler_service


def test_run_due_jobs_calls_watch_then_schedules(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler_service, "_run_regulatory_watch", lambda db: calls.append("watch"))
    monkeypatch.setattr(scheduler_service, "run_due_schedules", lambda db: calls.append("schedules"))

    scheduler_service._run_due_jobs()

    assert calls == ["watch", "schedules"]


def test_run_due_jobs_swallows_exceptions(monkeypatch):
    """Un tick en echec ne doit jamais remonter : sinon la boucle appelante
    mourrait et plus aucune veille/planification ne s'executerait jamais."""
    def boom(db):
        raise RuntimeError("panne simulee")

    monkeypatch.setattr(scheduler_service, "_run_regulatory_watch", boom)
    monkeypatch.setattr(scheduler_service, "run_due_schedules", lambda db: None)

    scheduler_service._run_due_jobs()  # ne doit pas lever


def test_run_due_jobs_lock_prevents_concurrent_execution(monkeypatch):
    """Regression du risque releve en revue : sans verrou transactionnel,
    deux workers (ou deux threads) pourraient executer le meme tick en meme
    temps. Le second doit se retirer immediatement, pas attendre ni dupliquer
    le travail."""
    calls = []

    def slow_watch(db):
        calls.append(1)
        time.sleep(0.4)

    monkeypatch.setattr(scheduler_service, "_run_regulatory_watch", slow_watch)
    monkeypatch.setattr(scheduler_service, "run_due_schedules", lambda db: None)

    t1 = threading.Thread(target=scheduler_service._run_due_jobs)
    t2 = threading.Thread(target=scheduler_service._run_due_jobs)
    t1.start()
    time.sleep(0.05)  # laisser t1 prendre le verrou avant que t2 ne tente
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    # Le second thread n'a jamais execute le travail : il a trouve le verrou
    # deja pris et s'est retire sans attendre.
    assert calls == [1]


def test_scheduler_loop_recovers_from_tick_exceptions(monkeypatch):
    """La boucle ne doit jamais mourir sur une exception d'un tick — sinon un
    seul echec (reseau EUR-Lex, panne DB passagere...) arrete definitivement
    la veille et les campagnes planifiees jusqu'au prochain redemarrage."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "SCHEDULER_POLL_SECONDS", 0)

    compte = {"n": 0}

    def tick_en_echec():
        compte["n"] += 1
        raise RuntimeError("panne simulee")

    monkeypatch.setattr(scheduler_service, "_run_due_jobs", tick_en_echec)

    async def run():
        await asyncio.wait_for(scheduler_service.scheduler_loop(), timeout=0.3)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(run())

    # Plusieurs ticks ont eu lieu malgre l'exception systematique : la boucle
    # continue.
    assert compte["n"] >= 2
