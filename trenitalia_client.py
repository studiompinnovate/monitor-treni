"""
Client API per Trenitalia e ViaggiaTreno.
Interagisce con:
1. LeFrecce BFF API (disponibilità biglietti, offerte, posti liberi, prezzi)
2. ViaggiaTreno API (ritardo in tempo reale, binario, fermate)
"""

import datetime
import requests
from typing import Dict, Any, List, Optional


class TrenitaliaClient:
    BFF_BASE_URL = "https://www.lefrecce.it/Channels.Website.BFF.WEB/website"
    VIAGGIATRENO_URL = "http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno"

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

        for offset_val in [0, 10]:
            data = self.get_solutions(origin_id, arrival_id, iso_start, offset=offset_val, limit=10)
            if data and "solutions" in data:
                all_solutions.extend(data["solutions"])

        parsed_trains = []
        seen_train_keys = set()

        for item in all_solutions:
            sol = item.get("solution", {})
            dep_raw = sol.get("departureTime", "")
            arr_raw = sol.get("arrivalTime", "")

            # Controlla che appartenga alla data richiesta
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
            primary_num = str(trains[-1].get("name", "")).strip() if not is_direct else str(trains[0].get("name", "")).strip()

            key = f"{dep_time}_{full_desc}"
            if key in seen_train_keys:
                continue
            seen_train_keys.add(key)

            price_val = sol.get("price", {}).get("amount") if sol.get("price") else None
            status = sol.get("status", "N/D")

            parsed_trains.append({
                "orario_partenza": dep_time,
                "orario_arrivo": arr_time,
                "durata": sol.get("duration", "N/D"),
                "descrizione_treni": full_desc,
                "numero_treno_principale": primary_num,
                "categoria_principale": trains[-1].get("trainCategory", "Treno") if not is_direct else trains[0].get("trainCategory", "Treno"),
                "diretto": is_direct,
                "num_cambi": len(trains) - 1,
                "prezzo_minimo": price_val,
                "stato": status,
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
        inclusi i singoli servizi (Posto a sedere, Cuccetta, Vagone letto)
        e il numero di posti disponibili per ciascuno.
        """
        if not solutions_data:
            return None

        solutions = solutions_data.get("solutions", [])
        for item in solutions:
            sol = item.get("solution", {})
            trains = sol.get("trains", [])
            train_names = [str(t.get("name", "")).strip() for t in trains]

            if target_train_number in train_names:
                # Estraiamo i dettagli principali
                dep_raw = sol.get("departureTime", "")
                arr_raw = sol.get("arrivalTime", "")
                
                # Formattazione orari
                dep_formatted = dep_raw[11:16] if len(dep_raw) >= 16 else dep_raw
                arr_formatted = arr_raw[11:16] if len(arr_raw) >= 16 else arr_raw

                min_price = sol.get("price", {}).get("amount") if sol.get("price") else None
                status = sol.get("status", "SCONOSCIUTO")
                duration = sol.get("duration", "N/D")

                # Analisi dettagliata servizi e offerte
                parsed_services = []
                grids = item.get("grids", [])
                for grid in grids:
                    for srv in grid.get("services", []):
                        s_name = srv.get("name", "Servizio")
                        s_group = srv.get("groupName", "")
                        offers_list = []

                        for off in srv.get("offers", []):
                            off_name = off.get("name", "Offerta")
                            off_status = off.get("status", "N/D")
                            avail_amount = off.get("availableAmount", 0)
                            price_val = off.get("price", {}).get("amount") if off.get("price") else None

                            offers_list.append({
                                "nome_offerta": off_name,
                                "stato": off_status,
                                "posti_disponibili": avail_amount,
                                "prezzo": price_val
                            })

                        parsed_services.append({
                            "servizio": s_name,
                            "gruppo": s_group,
                            "offerte": offers_list
                        })

                return {
                    "treno_numero": target_train_number,
                    "treno_categoria": trains[0].get("trainCategory", "InterCityNotte") if trains else "InterCityNotte",
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

    def get_viaggiatreno_live(self, train_number: str = "757", origin_code: str = "S00219") -> Optional[Dict[str, Any]]:
        """
        Recupera i dati in tempo reale da ViaggiaTreno per il treno odierno:
        - Ritardo in minuti
        - Stazione ultimo rilevamento
        - Orario e binario di partenza/arrivo
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*"
        }

        # 1. Trova l'id univoco del treno odierno
        auto_url = f"{self.VIAGGIATRENO_URL}/cercaNumeroTrenoTrenoAutocomplete/{train_number}"
        try:
            r = requests.get(auto_url, headers=headers, timeout=self.timeout)
            if r.status_code != 200 or not r.text.strip():
                return None

            # Es: 757 - TORINO PORTA NUOVA - 02/11/26|757-S00219-1793574000000
            line = r.text.strip().split("\n")[0]
            parts = line.split("|")
            if len(parts) < 2:
                return None

            train_id = parts[1].strip()
            # 2. Richiedi andamento del treno
            # URL formato: /andamentoTreno/{originCode}/{trainNumber}/{timestamp}
            subparts = train_id.split("-")
            if len(subparts) == 3:
                num, orig, ts = subparts
                andamento_url = f"{self.VIAGGIATRENO_URL}/andamentoTreno/{orig}/{num}/{ts}"
            else:
                andamento_url = f"{self.VIAGGIATRENO_URL}/andamentoTreno/{origin_code}/{train_number}"

            r2 = requests.get(andamento_url, headers=headers, timeout=self.timeout)
            if r2.status_code == 200:
                data = r2.json()
                return {
                    "numero": train_number,
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
            return None
        except Exception as e:
            print(f"Errore ViaggiaTreno live: {e}")
            return None
