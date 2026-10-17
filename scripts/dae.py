#!/usr/bin/env python3
"""Télécharge la base nationale officielle Géo'DAE (défibrillateurs), la filtre
sur l'Île-de-France et la réduit à un fichier compact : data/dae-idf.json

Le script s'adapte tout seul aux noms de colonnes du fichier officiel (ils
peuvent changer), et affiche ce qu'il a trouvé pour qu'on puisse vérifier.
Pour couvrir d'autres départements, changez la variable DEPTS ci-dessous.
"""
import csv, io, json, os, re, sys, urllib.request

# Ressources stables du jeu de données « Géo'DAE » sur data.gouv.fr
CSV_URL = "https://www.data.gouv.fr/api/1/datasets/r/edb6a9e1-2f16-4bbf-99e7-c3eb6b90794c"
DEPTS = {"75", "77", "78", "91", "92", "93", "94", "95"}  # Île-de-France
# Repli géographique si aucun code postal exploitable : grande boîte Île-de-France
BBOX = (48.10, 49.30, 1.40, 3.60)  # lat_min, lat_max, lon_min, lon_max
UA = {"User-Agent": "departs-proches/1.0 (+github actions; defibrillateurs)"}
OUT = "data/dae-idf.json"


def download(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
        raw = r.read()
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def pick(headers, *patterns):
    """Renvoie le nom de colonne qui correspond le mieux à l'un des motifs."""
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for h in headers:
            if rx.search(h or ""):
                return h
    return None


def num(v):
    if v is None:
        return None
    v = str(v).strip().replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def main():
    text = open(sys.argv[1], encoding='utf-8').read() if len(sys.argv) > 1 else download(CSV_URL)
    # délimiteur : on teste ; puis ,
    sample = text[:4000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    headers = reader.fieldnames or []
    if len(headers) < 2:  # mauvais délimiteur
        reader = csv.DictReader(io.StringIO(text), delimiter="," if delim == ";" else ";")
        headers = reader.fieldnames or []
    print("Colonnes détectées :", headers)

    col_lat = pick(headers, r"^lat", r"latitude", r"_lat", r"\blat\b", r"^y$|wgs.*y|geo.*y")
    col_lon = pick(headers, r"^lon", r"^lng", r"longitude", r"_lon|_lng", r"\blon\b", r"^x$|wgs.*x|geo.*x")
    col_geo = pick(headers, r"geo_?point|coordonn|geometry|the_geom|wkt")
    col_name = pick(headers, r"denomination|nom.*site|nom.*lieu|lieu|libell", r"(?:^|_)nom(?:$|_)|name")
    col_prec = pick(headers, r"prec|complement|detail|repere|situation|emplacement|localisation|acc.*lib|adr.*comp")
    col_cp = pick(headers, r"postal|code.?post|(?:^|_)cp(?:$|_)")
    col_dep = pick(headers, r"departement|(?:^|_)dep(?:t|$|_)")
    col_insee = pick(headers, r"insee|com.?insee|code.?commune")
    col_state = pick(headers, r"etat|fonct|statut|actif|service")
    col_acc = pick(headers, r"acc.*lib|acces|public|ouvert.*public")
    col_hours = pick(headers, r"disp.*j|jour|horaire|dispo|ouvert|plage|h24|24.?24|7.?7")
    col_indoor = pick(headers, r"interieur|exterieur|indoor|outdoor|implant|etage|position|voie")
    print("lat=%s lon=%s geo=%s nom=%s precision=%s cp=%s dep=%s" %
          (col_lat, col_lon, col_geo, col_name, col_prec, col_cp, col_dep))

    out, seen, scanned = [], set(), 0
    for row in reader:
        scanned += 1
        lat = num(row.get(col_lat)) if col_lat else None
        lon = num(row.get(col_lon)) if col_lon else None
        if (lat is None or lon is None) and col_geo:
            g = str(row.get(col_geo) or "")
            m = re.findall(r"-?\d+[.,]\d+", g)
            if len(m) >= 2:
                a, b = num(m[0]), num(m[1])
                # GeoJSON / WKT = lon,lat ; sinon lat,lon. On range par plausibilité.
                if a is not None and b is not None:
                    lat, lon = (a, b) if 40 < a < 52 else (b, a)
        if lat is None or lon is None:
            continue
        if not (40 < lat < 52 and -6 < lon < 11):
            continue
        # Filtre Île-de-France : code postal, puis département, puis boîte géo
        keep = False
        cp = str(row.get(col_cp) or "").strip() if col_cp else ""
        dep = str(row.get(col_dep) or "").strip() if col_dep else ""
        insee = str(row.get(col_insee) or "").strip() if col_insee else ""
        if cp[:2] in DEPTS:
            keep = True
        elif dep in DEPTS or dep.zfill(2) in DEPTS:
            keep = True
        elif insee[:2] in DEPTS:
            keep = True
        elif not (col_cp or col_dep or col_insee):
            keep = BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lon <= BBOX[3]
        if not keep:
            continue
        if col_state:
            st = str(row.get(col_state) or "").lower()
            if re.search(r"hors.?service|non.?fonct|a.?repar|retir|supprim|inactif|desinstall|hs\b", st):
                continue
        key = f"{lat:.5f}|{lon:.5f}"
        if key in seen:
            continue
        seen.add(key)

        name = ((col_name and row.get(col_name)) or (col_prec and row.get(col_prec)) or "").strip()
        prec = (col_prec and row.get(col_prec) or "").strip()
        if prec and prec != name:
            name = (name + " — " + prec) if name else prec
        if not name:
            name = "Défibrillateur"
        rec = {"n": name[:120], "lat": round(lat, 5), "lon": round(lon, 5)}
        acc = (col_acc and str(row.get(col_acc) or "").lower()) or ""
        if re.search(r"public|libre|tout|oui|24", acc):
            rec["a"] = "public"
        elif re.search(r"priv|restrein|client|interne", acc):
            rec["a"] = "prive"
        ind = (col_indoor and str(row.get(col_indoor) or "").lower()) or ""
        if re.search(r"ext|dehors|voie|rue|outdoor", ind):
            rec["i"] = 0
        elif re.search(r"int|dedans|batiment|indoor", ind):
            rec["i"] = 1
        h = (col_hours and str(row.get(col_hours) or "").lower()) or ""
        if re.search(r"24\D{0,3}24|7\D{0,3}7|permanent|h24|tout le temps|24.?7", h):
            rec["h"] = "24/7"
        elif h and not re.search(r"^(nc|non|inconnu|\s*)$", h):
            rec["h"] = "lim"
        out.append(rec)

    print(f"{scanned} lignes lues, {len(out)} défibrillateurs retenus en Île-de-France.")
    if len(out) < 100:
        sys.exit("Trop peu de résultats : le filtrage ou la détection des colonnes a échoué. "
                 "Vérifiez les colonnes affichées ci-dessus.")
    os.makedirs("data", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": int(__import__("time").time()), "zone": sorted(DEPTS), "dae": out},
                  f, ensure_ascii=False, separators=(",", ":"))
    sz = os.path.getsize(OUT)
    print(f"{OUT} écrit ({sz // 1024} Ko).")


if __name__ == "__main__":
    main()
