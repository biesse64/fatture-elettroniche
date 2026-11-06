"""
Controllo di codice fiscale e partita IVA italiani (carattere di controllo).

Stesse regole di static/controlli.js, che le applica mentre si scrive: qui valgono al salvataggio
del cliente e prima di creare l'XML, per non farsi scartare la fattura dallo SDI.
Le funzioni restituiscono None se il dato e' corretto, altrimenti la frase da mostrare.
"""
import re

_DISPARI = dict(zip("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                    [1, 0, 5, 7, 9, 13, 15, 17, 19, 21] +
                    [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23]))
_PARI = {c: (int(c) if c.isdigit() else ord(c) - 65) for c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
# cifre sostituibili da lettere nei codici omocodici
_N = "[0-9LMNPQRSTUV]"
_FORMA_CF = re.compile(rf"^[A-Z]{{6}}{_N}{{2}}[ABCDEHLMPRST]{_N}{{2}}[A-Z]{_N}{{3}}[A-Z]$")


def pulisci_piva(piva):
    """Toglie spazi e il prefisso IT che spesso si copia insieme al numero."""
    p = re.sub(r"[\s.\-]", "", piva or "").upper()
    return p[2:] if p.startswith("IT") and p[2:].isdigit() else p


def controlla_piva(piva):
    p = pulisci_piva(piva)
    if not re.fullmatch(r"\d{11}", p):
        return "La partita IVA italiana ha 11 cifre."
    if p == "0" * 11:
        return "La partita IVA non è valida."
    somma = 0
    for i, c in enumerate(p[:10]):
        n = int(c)
        if i % 2:
            n *= 2
            n -= 9 if n > 9 else 0
        somma += n
    if (10 - somma % 10) % 10 != int(p[10]):
        return "La partita IVA non è valida: c'è una cifra sbagliata o invertita."
    return None


def controlla_cf(cf):
    c = re.sub(r"\s", "", cf or "").upper()
    if re.fullmatch(r"\d{11}", c):                   # societa', enti, studi: stesso controllo della partita IVA
        errore = controlla_piva(c)
        return errore and "Il codice fiscale numerico non è valido: c'è una cifra sbagliata o invertita."
    if len(c) != 16:
        return "Il codice fiscale ha 16 caratteri (o 11 cifre per società ed enti)."
    if not _FORMA_CF.match(c):
        return "Il codice fiscale non ha la forma giusta: controlla lettere e numeri."
    somma = sum(_DISPARI[x] if i % 2 == 0 else _PARI[x] for i, x in enumerate(c[:15]))
    if chr(65 + somma % 26) != c[15]:
        return "Il codice fiscale non è valido: c'è un carattere sbagliato."
    return None
