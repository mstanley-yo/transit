import requests
import bs4
from bs4 import BeautifulSoup
from dataclasses import dataclass
import datetime
import pandas as pd
import argparse
from pathlib import Path

URLS_WKDAY = {
    "二子玉川": "https://transfer.navitime.biz/tokyu/pc/diagram/TrainDiagram?stCd=00007197&rrCd=00000787&updown=0",
    "大岡山": "https://transfer.navitime.biz/tokyu/pc/diagram/TrainDiagram?stCd=00005529&rrCd=00000791&updown=0",
}

@dataclass
class HourData:
    minute: int
    url: str

@dataclass
class ParsedTimetable:
    data: dict[int, list[HourData]]
    departure: str

def select_to_tag(data: bs4.element.ResultSet | None) -> bs4.element.Tag:
    if not data:
        raise Exception("could not find results matching select")

    if len(data) != 1:
        raise Exception(f"expected one match, got:\n{data}")

    tag = data[0]
    if not isinstance(tag, bs4.element.Tag):
        raise Exception(f"expected bs4.element.Tag, got {type(data)}")
    return tag

def parse_timetable_url(url: str) -> ParsedTimetable:
    """Parse a timetale url into a ParsedTimetable"""
    out = {}
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "lxml")

    station_text = soup.select("#diagram-summary > div.summary > div")
    station = select_to_tag(station_text).get_text()

    timetable_list = soup.select("#diagram-table-weekday > dl")
    timetable = select_to_tag(timetable_list)
    current_hour = -1
    for child in timetable.children:
        if not isinstance(child, bs4.element.Tag):
            continue
       
        # extract current hour from dt (hour column on table)
        if child.name == "dt": 
            current_hour = dt_to_hour(child)
        
        # extract minute from dd (minute column on table)
        if child.name == "dd":
            current_minutes = dd_to_minutes(child)
            if current_hour == -1:
                raise Exception("expected dt tag first but found dd tag first")
            if current_hour in out:
                raise Exception(f"expected hour {current_hour} to already be handled, but got it twice")
            out[current_hour] = current_minutes
    return ParsedTimetable(data=out, departure=station)

def dt_to_hour(tag: bs4.element.Tag) -> int:
    text = tag.select("div:nth-child(1)")
    hour = select_to_tag(text).get_text()
    return int(hour)

def dd_to_minutes(tag: bs4.element.Tag) -> list[HourData]:
    minute_data = []
    for element in tag.children: 
        if not isinstance(element, bs4.element.Tag):
            continue

        link = element["href"]
        url = f"https://transfer.navitime.biz/{link}"

        minute_text = element.select("a > div.minute-area > div.minute")
        minute = int(select_to_tag(minute_text).get_text())

        minute_data.append(HourData(minute=minute, url=url))
    return minute_data

@dataclass
class StopInfo:
    stop: str
    time: datetime.datetime

def get_arrival(url: str, target: str) -> StopInfo:
    """get arrival of train at a station"""
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "lxml")
    diagram_area = select_to_tag(soup.select("#diagram-area"))
    stop_list = diagram_area.select("div.stop-info")

    for stop in stop_list:
        name = select_to_tag(stop.select("div.name")).get_text()
        if name == target:
            time_str = select_to_tag(stop.select("div.time > div > span:nth-child(1)")).get_text()
            t = datetime.datetime.strptime(time_str, "%H:%M").time()
            time = datetime.datetime.combine(datetime.date.today(), t)
            return StopInfo(stop=name, time=time)
    raise Exception(f"Could not find '{target}' in stop list")

@dataclass
class TrainData:
    departure: str
    departure_time: datetime.datetime
    arrival: str
    arrival_time: datetime.datetime

def build_timetable(departure: str, arrival: str) -> list[TrainData]:
    out = []
    departure_url = URLS_WKDAY[departure]
    parsed = parse_timetable_url(departure_url)
    for departure_hour, minute_data_list in parsed.data.items():
        for minute_data in minute_data_list:
            t = datetime.time(hour=departure_hour, minute=minute_data.minute)
            departure_time = datetime.datetime.combine(datetime.date.today(), t)

            print(f"getting arrival for train departing at {departure_time}")
            arrival_data = get_arrival(minute_data.url, arrival)
            arrival, arrival_time = arrival_data.stop, arrival_data.time
            arrival_time = correct_date_flip(departure_time, arrival_time)
            out.append(TrainData(
                departure=departure,
                departure_time=departure_time,
                arrival=arrival,
                arrival_time=arrival_time
            ))
    return out

def correct_date_flip(dep: datetime.datetime, arr: datetime.datetime) -> datetime.datetime:
    if arr - dep < datetime.timedelta(0):
        arr += datetime.timedelta(days=1)
    return arr

def timetable_to_pandas(table: list[TrainData]) -> pd.DataFrame:
    """Convert a list of TrainData into a DataFrame"""
    return pd.DataFrame([
        {
            "departure": train.departure,
            "departure_time": train.departure_time,
            "arrival": train.arrival,
            "arrival_time": train.arrival_time,
        }
        for train in table
    ])

def pandas_to_timetable(df: pd.DataFrame) -> list[TrainData]:
    """Convert a DataFrame back into a list of TrainData"""
    return [
        TrainData(
            departure=str(row["departure"]),
            departure_time=parse_dt_str(str(row["departure_time"])),
            arrival=str(row["arrival"]),
            arrival_time=parse_dt_str(str(row["arrival_time"]))
        )
        for _, row in df.iterrows()
    ]

def parse_dt_str(s: str) -> datetime.datetime:
    dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    return dt

def sync_timetables() -> None:
    Path("data").mkdir(exist_ok=True)

    print("=== Syncing timetable for 二子玉川 to 大岡山===")
    ft2ok_raw = build_timetable("二子玉川", "大岡山") 
    ft2ok = timetable_to_pandas(ft2ok_raw)
    ft2ok.to_csv("./data/futakotamagawa_to_ookayama_timetable.csv")
    print("=== Done ===")

    print("=== Syncing timetable for 大岡山 to 目黒===")
    ok2mg_raw = build_timetable("大岡山", "目黒") 
    ok2mg = timetable_to_pandas(ok2mg_raw)
    ok2mg.to_csv("./data/ookayama_to_meguro_timetable.csv")
    print("=== Done ===")

@dataclass
class Route:
    departure_time: datetime.datetime
    transfer_arrival_time: datetime.datetime
    transfer_waittime: datetime.timedelta
    transfer_departure_time: datetime.datetime
    arrival_time: datetime.datetime
    total_time: datetime.timedelta

def calculate_transfer(table1: list[TrainData], table2: list[TrainData]) -> list[Route]:
    routes: list[Route] = []

    for t1 in table1:
        best_route: Route | None = None

        for t2 in table2:
            wait_time = t2.departure_time - t1.arrival_time
            if wait_time < datetime.timedelta(minutes=1):
                continue

            total_time = t2.arrival_time - t1.departure_time

            if best_route is None or t2.arrival_time < best_route.arrival_time:
                best_route = Route(
                    departure_time=t1.departure_time,
                    transfer_arrival_time=t1.arrival_time,
                    transfer_waittime=wait_time,
                    transfer_departure_time=t2.departure_time,
                    arrival_time=t2.arrival_time,
                    total_time=total_time,
                )

        if best_route is not None:
            routes.append(best_route)

    return routes

def routes_to_pandas(routes: list[Route]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "departure_time": route.departure_time,
            "transfer_arrival_time": route.transfer_arrival_time,
            "transfer_waittime": route.transfer_waittime,
            "transfer_departure_time": route.transfer_departure_time,
            "arrival_time": route.arrival_time,
            "total_time": route.total_time,
        }
        for route in routes
    ])

def parse_td_str(s: str) -> datetime.timedelta:
    days_part, time_part = s.split(" days ")
    hours, minutes, seconds = map(int, time_part.split(":"))
    return datetime.timedelta(days=int(days_part), hours=hours, minutes=minutes, seconds=seconds)

def pandas_to_routes(df: pd.DataFrame) -> list[Route]:
    return [
        Route(
            departure_time=parse_dt_str(str(row["departure_time"])),
            transfer_arrival_time=parse_dt_str(str(row["transfer_arrival_time"])),
            transfer_waittime=parse_td_str(str(row["transfer_waittime"])),
            transfer_departure_time=parse_dt_str(str(row["transfer_departure_time"])),
            arrival_time=parse_dt_str(str(row["arrival_time"])),
            total_time=parse_td_str(str(row["total_time"])),
        )
        for _, row in df.iterrows()
    ]

def print_routes_table(routes: list[Route]) -> None:
    def fmt_time(dt: datetime.datetime) -> str:
        return dt.strftime("%H:%M")

    def fmt_delta(td: datetime.timedelta) -> str:
        total_minutes = int(td.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours:02}:{minutes:02}"

    headers = ["Departure", "Transfer Arrival", "Wait", "Transfer Departure", "Arrival", "Total Time"]
    rows = [
        [
            fmt_time(route.departure_time),
            fmt_time(route.transfer_arrival_time),
            fmt_delta(route.transfer_waittime),
            fmt_time(route.transfer_departure_time),
            fmt_time(route.arrival_time),
            fmt_delta(route.total_time),
        ]
        for route in routes
    ]

    col_widths = [
        max(len(header), max((len(row[i]) for row in rows), default=0))
        for i, header in enumerate(headers)
    ]

    def fmt_row(values: list[str]) -> str:
        return "| " + " | ".join(v.center(col_widths[i]) for i, v in enumerate(values)) + " |"

    def fmt_separator() -> str:
        return "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

    print(fmt_separator())
    print(fmt_row(headers))
    print(fmt_separator())
    for row in rows:
        print(fmt_row(row))
    print(fmt_separator())

def print_routes_table_compact(routes: list[Route]) -> None:
    def fmt_time(dt: datetime.datetime) -> str:
        return dt.strftime("%H:%M")

    def fmt_delta(td: datetime.timedelta) -> str:
        total_minutes = int(td.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours:02}:{minutes:02}"

    headers = ["Dep.", "Arr.", "Wait", "Dep.", "Arr.", "Total"]
    rows = [
        [
            fmt_time(route.departure_time),
            fmt_time(route.transfer_arrival_time),
            fmt_delta(route.transfer_waittime),
            fmt_time(route.transfer_departure_time),
            fmt_time(route.arrival_time),
            fmt_delta(route.total_time),
        ]
        for route in routes
    ]

    col_widths = [
        max(len(header), max((len(row[i]) for row in rows), default=0))
        for i, header in enumerate(headers)
    ]

    def fmt_row(values: list[str]) -> str:
        return "| " + " | ".join(v.center(col_widths[i]) for i, v in enumerate(values)) + " |"

    def fmt_separator() -> str:
        return "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

    print(fmt_separator())
    print(fmt_row(["Leg 1", "", "", "Leg 2", "", ""]))
    print(fmt_row(headers))
    print(fmt_separator())
    for row in rows:
        print(fmt_row(row))
    print(fmt_separator())

def main():
    parser = argparse.ArgumentParser(
        description="Train route transfer calculator",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-sync", action="store_true", help="Sync timetables from source")
    parser.add_argument("-pretty", action="store_true", help="Read from data/routes.csv and print as wide table")
    parser.add_argument("-print", action="store_true", dest="print_compact", help="Read from data/routes.csv and print as compact table")

    args = parser.parse_args()

    if args.sync:
        sync_timetables()

        df1 = pd.read_csv("./data/futakotamagawa_to_ookayama_timetable.csv")
        table1 = pandas_to_timetable(df1)

        df2 = pd.read_csv("./data/ookayama_to_meguro_timetable.csv")
        table2 = pandas_to_timetable(df2)

        routes = calculate_transfer(table1, table2)
        timetable = routes_to_pandas(routes)
        timetable.to_csv("./data/routes.csv", index=False)
        print("Timetables synced and saved to data/routes.csv")

    elif args.pretty:
        df = pd.read_csv("./data/routes.csv")
        routes = pandas_to_routes(df)
        print_routes_table(routes)

    elif args.print_compact:
        df = pd.read_csv("./data/routes.csv")
        routes = pandas_to_routes(df)
        print_routes_table_compact(routes)

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
