"""
Client API per Trenitalia, ViaggiaTreno e Italo Live.
Interagisce con:
1. LeFrecce BFF API (disponibilità biglietti, offerte, posti liberi, prezzi Trenitalia)
2. ViaggiaTreno API (ritardo in tempo reale Trenitalia, binario, fermate)
3. Italo In Viaggio API (stato treno e ritardi per treni Italo)
"""

import datetime
import requests
from typing import Dict, Any, List, Optional


class TrenitaliaClient:
    BFF_BASE_URL = "https://www.lefrecce.it/Channels.Website.BFF.WEB/website"
    VIAGGIATRENO_URL = "http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno"
    ITALO_LIVE_URL = "https://italoinviaggio.italotreno.com/api/RicercaTrenoService"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://www.lefrecce.it",
            "Referer": "https://www.lefrecce.it/"
        })

    def search_station(self, name: str) -> List[Dict[str, Any]]:
        """Cerca l'ID di una stazione Trenitalia dal nome."""
        url = f"{self.BFF_BASE_URL}/locations/search"
        try:
            r = self.session.get(url, params={"name": name}, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
            return []
        except Exception as e:
            print(f"Errore ricerca stazione '{name}': {e}")
            return []

    def get_solutions(
        self,
        departure_id: int,
        arrival_id: int,
        departure_iso_date: str,
        adults: int = 1,
        children: int = 0,
        offset: int = 0,
        limit: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        Interroga le soluzioni di viaggio Trenitalia.
        departure_iso_date es: '2026-12-21T20:00:00.000+01:00'
        """
        url = f"{self.BFF_BASE_URL}/ticket/solutions"
        payload = {
            "departureLocationId": departure_id,
            "arrivalLocationId": arrival_id,
            "departureTime": departure_iso_date,
            "adults": adults,
            "children": children,
            "criteria": {
                "frecceOnly": False,
                "regionalOnly": False,
                "noChanges": False,
                "order": "DEPARTURE_DATE",
                "limit": limit,
                "offset": offset
            },
            "advancedSearchRequest": {
                "bestFare": False
            }
        }

        try:
            r = self.session.post(url, json=payload, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
            else:
                print(f"Errore chiamata Trenitalia soluzioni: HTTP {r.status_code}")
                return None
        except Exception as e:
            print(f"Eccezione durante la richiesta a Trenitalia: {e}")
            return None

    def get_day_trains_summary(
        self,
        origin_id: int,
        arrival_id: int,
        date_str: str
    ) -> List[Dict[str, Any]]:
        """
        Recupera l'elenco di tutte le soluzioni di viaggio per una data specifica (YYYY-MM-DD).
        Restituisce un riepilogo con orari, numeri di treno e prezzi.
        """
        iso_start = f"{date_str}T04:00:00.000+01:00"
        all_solutions = []

        for offset_val in [0, 10, 20]:
            data = self.get_solutions(origin_id, arrival_id, iso_start, offset=offset_val, limit=10)
            if data and "solutions" in data:
                sols = data["solutions"]
                all_solutions.extend(sols)
                if len(sols) < 10:
                    break
            else:
                break

        parsed_trains = []
        seen_train_keys = set()

        for item in all_solutions:
            sol = item.get("solution", {})
            dep_raw = sol.get("departureTime", "")
            arr_raw = sol.get("arrivalTime", "")

            if not dep_raw.startswith(date_str):
                continue

            trains = sol.get("trains", [])
            if not trains:
                continue

            dep_time = dep_raw[11:16]
            arr_time = arr_raw[11:16]
            is_direct = len(trains) == 1

            train_descriptions = []
            for t in trains:
                cat = t.get("trainCategory", "")
                num = t.get("name", "")
                train_descriptions.append(f"{cat} {num}".strip())

            full_desc = " + ".join(train_descriptions)
            primary_num = str(trains[0].get("name", "")).strip() if is_direct else str(trains[-1].get("name", "")).strip()

            key = f"{dep_time}_{full_desc}"
            if key in seen_train_keys:
                continue
            seen_train_keys.add(key)

            # Calcolo rigoroso del prezzo reale sommando tutte le tratte/treni del viaggio
            grids = item.get("grids", [])
            legs_prices = []
            is_all_legs_saleable = (sol.get("status") == "SALEABLE")

            for g in grids:
                valid_p = [
                    o["price"]["amount"]
                    for s in g.get("services", [])
                    for o in s.get("offers", [])
                    if o.get("status") == "SALEABLE"
                    and o.get("price")
                    and o["price"].get("amount") is not None
                    and o["price"].get("amount") > 0
                ]
                if valid_p:
                    legs_prices.append(min(valid_p))
                else:
                    is_all_legs_saleable = False
                    legs_prices.append(None)

            raw_bundle = sol.get("price", {}).get("amount") if sol.get("price") else None

            # Se tutti i treni hanno posti acquistabili, il prezzo è la somma di ogni treno
            if is_all_legs_saleable and all(p is not None for p in legs_prices) and legs_prices:
                total_price = round(sum(legs_prices), 2)
                breakdown_str = " + ".join(f"{p:.2f} €" for p in legs_prices)
                status = "SALEABLE"
                is_saleable = True
            elif is_all_legs_saleable and raw_bundle and not grids:
                total_price = round(raw_bundle, 2)
                breakdown_str = f"{total_price:.2f} €"
                status = "SALEABLE"
                is_saleable = True
            else:
                total_price = None
                breakdown_str = ""
                status = "SOLD_OUT"
                is_saleable = False

            parsed_trains.append({
                "orario_partenza": dep_time,
                "orario_arrivo": arr_time,
                "durata": sol.get("duration", "N/D"),
                "descrizione_treni": full_desc,
                "numero_treno_principale": primary_num,
                "categoria_principale": trains[0].get("trainCategory", "Treno") if is_direct else trains[-1].get("trainCategory", "Treno"),
                "diretto": is_direct,
                "num_cambi": len(trains) - 1,
                "prezzo_minimo": total_price,
                "dettaglio_prezzi": legs_prices,
                "dettaglio_str": breakdown_str,
                "prezzo_bundle": raw_bundle,
                "stato": status,
                "acquistabile": is_saleable,
                "tutti_i_treni": trains
            })

        parsed_trains.sort(key=lambda x: x["orario_partenza"])
        return parsed_trains

    def find_target_train(
        self,
        solutions_data: Dict[str, Any],
        target_train_number: str = "757"
    ) -> Optional[Dict[str, Any]]:
        """
        Estrae le informazioni dettagliate sul treno cercato (es. 757)
        inclusi i singoli servizi specifici di quel treno (es. Posto a sedere, Cuccetta, Vagone letto)
        e il numero di posti disponibili per ciascuno.
        Evita di mescolare i servizi di altri treni in caso di soluzioni con cambi.
        """
        if not solutions_data:
            return None

        target_train_number = str(target_train_number).strip()
        solutions = solutions_data.get("solutions", [])
        for item in solutions:
            sol = item.get("solution", {})
            trains = sol.get("trains", [])
            train_names = [str(t.get("name", "")).strip() for t in trains]

            if target_train_number in train_names:
                target_idx = train_names.index(target_train_number)
                target_train_obj = trains[target_idx]
                treno_cat = target_train_obj.get("trainCategory") or target_train_obj.get("denomination", "Treno")

                # Formattazione orari
                dep_raw = sol.get("departureTime", "")
                arr_raw = sol.get("arrivalTime", "")
                dep_formatted = dep_raw[11:16] if len(dep_raw) >= 16 else dep_raw
                arr_formatted = arr_raw[11:16] if len(arr_raw) >= 16 else arr_raw

                min_price = sol.get("price", {}).get("amount") if sol.get("price") else None
                status = sol.get("status", "SCONOSCIUTO")
                duration = sol.get("duration", "N/D")

                # Seleziona la grid specifica del treno cercato
                grids = item.get("grids", [])
                target_grid = None
                if len(grids) == len(trains) and target_idx < len(grids):
                    target_grid = grids[target_idx]
                elif grids:
                    target_grid = grids[0]

                # Raggruppa le offerte per ogni servizio unico
                parsed_services = []
                if target_grid:
                    for srv in target_grid.get("services", []):
                        s_name = srv.get("name", "Servizio")
                        s_group = srv.get("groupName", "")

                        max_seats = 0
                        min_srv_price = None
                        srv_status = "SOLD_OUT"
                        offers_list = []

                        for off in srv.get("offers", []):
                            off_name = off.get("name", "Offerta")
                            off_status = off.get("status", "N/D")
                            avail = off.get("availableAmount", 0)
                            p_val = off.get("price", {}).get("amount") if off.get("price") else None

                            if avail > max_seats:
                                max_seats = avail
                            if off_status == "SALEABLE":
                                srv_status = "SALEABLE"
                            if p_val is not None:
                                if min_srv_price is None or p_val < min_srv_price:
                                    min_srv_price = p_val

                            offers_list.append({
                                "nome_offerta": off_name,
                                "stato": off_status,
                                "posti_disponibili": avail,
                                "prezzo": p_val
                            })

                        parsed_services.append({
                            "servizio": s_name,
                            "gruppo": s_group,
                            "stato": srv_status,
                            "posti_disponibili": max_seats,
                            "prezzo_minimo": min_srv_price,
                            "offerte": offers_list
                        })

                tutti_i_nomi = [f"{t.get('trainCategory', '')} {t.get('name', '')}".strip() for t in trains]
                desc_tratta = " + ".join(tutti_i_nomi) if len(trains) > 1 else f"{treno_cat} {target_train_number}"

                return {
                    "treno_numero": target_train_number,
                    "treno_categoria": treno_cat,
                    "descrizione_soluzione": desc_tratta,
                    "num_cambi": len(trains) - 1,
                    "origine": sol.get("origin", "Torino Porta Nuova"),
                    "destinazione": sol.get("destination", "Termoli"),
                    "orario_partenza": dep_formatted,
                    "orario_arrivo": arr_formatted,
                    "durata": duration,
                    "stato_vendita": status,
                    "prezzo_minimo": min_price,
                    "servizi": parsed_services,
                    "soluzione_id": sol.get("id")
                }

        return None

    def get_italo_live(self, train_number: str) -> Optional[Dict[str, Any]]:
        """Recupera lo stato live di un treno Italo da Italo In Viaggio."""
        url = f"{self.ITALO_LIVE_URL}?treno={train_number}"
        try:
            r = requests.get(url, timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                ts = data.get("TrainSchedule", {})
                if ts and ts.get("TrainNumber"):
                    delay_val = ts.get("DistruptionMin")
                    try:
                        ritardo_min = int(delay_val) if delay_val is not None else 0
                    except (ValueError, TypeError):
                        ritardo_min = 0

                    return {
                        "vettore": "Italo",
                        "numero": str(ts.get("TrainNumber")),
                        "origine": f"{ts.get('DepartureStationDescription', 'N/D')} ({ts.get('DepartureDate', '')})",
                        "destinazione": f"{ts.get('ArrivalStationDescription', 'N/D')} ({ts.get('ArrivalDate', '')})",
                        "ritardo": ritardo_min,
                        "stazione_ultimo_rilevamento": ts.get("LastPassageStationDescription") or "--",
                        "ora_ultimo_rilevamento": ts.get("LastPassageTime") or "--",
                        "binario_effettivo_partenza": None
                    }
            return None
        except Exception:
            return None

    def get_viaggiatreno_live(self, train_number: str = "757", origin_code: str = "S00219") -> Optional[Dict[str, Any]]:
        """
        Recupera i dati in tempo reale da ViaggiaTreno per il treno odierno.
        Se non trova il treno o se è un treno Italo, interpella Italo In Viaggio.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*"
        }

        # Controllo se è un treno Italo
        train_str = str(train_number).strip()
        if train_str.startswith("99") or train_str.startswith("81") or len(train_str) == 4 and train_str[0] in ("8", "9"):
            italo_data = self.get_italo_live(train_str)
            if italo_data:
                return italo_data

        auto_url = f"{self.VIAGGIATRENO_URL}/cercaNumeroTrenoTrenoAutocomplete/{train_str}"
        try:
            r = requests.get(auto_url, headers=headers, timeout=self.timeout)
            if r.status_code != 200 or not r.text.strip():
                # Fallback tentativo Italo
                return self.get_italo_live(train_str)

            line = r.text.strip().split("\n")[0]
            parts = line.split("|")
            if len(parts) < 2:
                return self.get_italo_live(train_str)

            train_id = parts[1].strip()
            subparts = train_id.split("-")
            if len(subparts) == 3:
                num, orig, ts = subparts
                andamento_url = f"{self.VIAGGIATRENO_URL}/andamentoTreno/{orig}/{num}/{ts}"
            else:
                andamento_url = f"{self.VIAGGIATRENO_URL}/andamentoTreno/{origin_code}/{train_str}"

            r2 = requests.get(andamento_url, headers=headers, timeout=self.timeout)
            if r2.status_code == 200:
                data = r2.json()
                return {
                    "vettore": "Trenitalia",
                    "numero": train_str,
                    "origine": data.get("origine"),
                    "destinazione": data.get("destinazione"),
                    "ritardo": data.get("ritardo", 0),
                    "stazione_ultimo_rilevamento": data.get("stazioneUltimoRilevamento", "--"),
                    "ora_ultimo_rilevamento": data.get("oraUltimoRilevamento"),
                    "binario_effettivo_partenza": data.get("binarioEffettivoPartenzaDescrizione"),
                    "binario_programmato_partenza": data.get("binarioProgrammatoPartenzaDescrizione"),
                    "in_stazione": data.get("inStazione", False),
                    "non_partito": data.get("nonPartito", False)
                }

            return self.get_italo_live(train_str)
        except Exception as e:
            return self.get_italo_live(train_str)
