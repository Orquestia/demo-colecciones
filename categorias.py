"""Lista común de categorías (módulo M2 de la Opción 1 / parte de M2 en la Opción 2).

Cada fuente nombra distinto ("Camisetas hombre", "camiseta-y-polos", "CAMISETAS 👕"); aquí se lleva
todo a una sola lista para que la vitrina se navegue igual sin importar el proveedor.
"""
import re
import unicodedata

# Orden = prioridad: la primera regla que coincide gana ("vestido de baño" antes que "vestido").
REGLAS = [
    # Accesorios que mencionan otra prenda ("colgante para bolso", "calcetín") van primero.
    ("Accesorios", ["colgante", "llavero", "estuche", "tarjetero", "calcetin", "charm"]),
    ("Vestidos de baño", ["vestido de bano", "vestidos de bano", "bano", "swimsuit", "bikini", "trikini"]),
    ("Perfumes", ["perfume", "locion", "fragancia", "eau de"]),
    ("Gorras", ["gorra", "cap", "sombrero", "beanie"]),
    ("Bolsos", ["bolso", "morral", "maleta", "rinonera", "cartera", "mochila", "bag", "tote"]),
    ("Zapatos y tenis", ["zapato", "tenis", "tennis", "sneaker", "bota", "botin", "sandalia", "alpargata", "mocasin", "tacon", "chancla"]),
    ("Buzos y sudaderas", ["buzo", "sudadera", "hoodie", "saco", "sweater", "cardigan", "camibuzo"]),
    ("Chaquetas", ["chaqueta", "abrigo", "jacket", "chaleco", "blazer"]),
    ("Camisas", ["camisa"]),
    ("Camisetas y polos", ["camiseta", "polo", "t-shirt", "tshirt", "blusa", "crop"]),
    ("Pantalonetas y shorts", ["pantaloneta", "short", "bermuda"]),
    ("Pantalones y jeans", ["pantalon", "jean", "jogger", "legging", "licra"]),
    ("Vestidos y faldas", ["vestido", "falda", "enterizo", "body", "bodys"]),
    ("Conjuntos y deportivo", ["conjunto", "set", "top", "deportiv", "alo", "lululemon"]),
    ("Accesorios", ["accesorio", "correa", "cinturon", "billetera", "gafa", "joya", "collar", "pulsera",
                    "medias", "reloj", "llavero", "arete", "anillo"]),
]
LISTA = list(dict.fromkeys(c for c, _ in REGLAS[1:]))  # orden de menú, sin repetir


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 -]+", " ", texto.replace("-", " "))


def categoria_comun(*textos):
    """Devuelve la categoría común para el primer texto que coincida con alguna regla, o None."""
    for texto in textos:
        n = f" {normalizar(texto)} "
        for categoria, claves in REGLAS:
            # Palabras cortas ("set", "top", "cap") deben ir completas; las largas aceptan plural.
            if any(re.search(rf"\b{re.escape(c)}" + ("" if len(c) >= 5 else r"(s|es)?\b"), n) for c in claves):
                return categoria
    return None


def genero(*textos):
    n = " ".join(normalizar(t) for t in textos)
    if re.search(r"\b(hombre|hombres|caballero|men)\b", n):
        return "Hombre"
    if re.search(r"\b(mujer|mujeres|dama|women|girl)\b", n):
        return "Mujer"
    return None
