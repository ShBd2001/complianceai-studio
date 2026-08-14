"""Conversion HTML -> PDF via un moteur de rendu reel (Chromium/Playwright).

Choix delibere plutot qu'une bibliotheque de conversion pure Python
(weasyprint, wkhtmltopdf) : ces dernieres exigent des bibliotheques systeme
(Pango/Cairo/GDK-Pixbuf ou un binaire externe) reputees difficiles a installer
de facon fiable, en particulier sous Windows. Playwright pilote un vrai
Chromium et rend le CSS moderne (polices web, degrades) fidelement.

Un navigateur est lance a chaque appel plutot que maintenu en arriere-plan :
la generation d'un rapport est une action explicite et occasionnelle, pas un
chemin a haute frequence — inutile de garder un processus Chromium ouvert en
permanence, surtout sur un plan d'hebergement a memoire limitee.
"""

from __future__ import annotations

from playwright.sync_api import sync_playwright


def html_to_pdf(html: str) -> bytes:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            # networkidle : laisse le temps aux polices Google Fonts de
            # charger avant l'impression, sans quoi le PDF se rabat sur les
            # polices systeme par defaut.
            page.set_content(html, wait_until="networkidle")
            return page.pdf(print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()
