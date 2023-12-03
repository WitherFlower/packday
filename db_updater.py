import os
from pprint import pprint
import psycopg2
import psycopg2.errors
import tomli
from typing import List
from dotenv import load_dotenv

load_dotenv()

# DB Setup

DB_PASSWORD = os.getenv("DB_PASSWORD")

conn = psycopg2.connect(
    host="localhost",
    database="unpack",
    user="postgres",
    password=DB_PASSWORD
)

# DB Calls


def set_current_pack_maps(pack_id: int, map_ids: List[int]):

    query = f"INSERT INTO maps (pack_id, beatmap_id) VALUES ({pack_id}, %s)"

    with conn.cursor() as cur:
        cur.executemany(query, map(lambda n: (n,), map_ids))
        conn.commit()


def remove_pack(pack_id: int):

    query = f"DELETE FROM maps WHERE pack_id={pack_id}"

    with conn.cursor() as cur:
        cur.execute(query)
        conn.commit()


def load_toml(pack_file: str) -> dict:
    with open(pack_file, "rb") as file:
        data = tomli.load(file)
        return data


# REMOVE BAD DATA
remove_pack(pack_id=2)


pack_data = load_toml("./packs/pack_2.toml")
set_current_pack_maps(2, pack_data['maps'])

for multiplier_data in pack_data['multipliers']:

    query = f"""UPDATE maps SET
        multiplier = {multiplier_data['multiplier']},
        mods = ARRAY{multiplier_data['mods']},
        exact_mods = {multiplier_data['exact']}
        WHERE beatmap_id = {multiplier_data['map_id']};
    """

    with conn.cursor() as cur:
        cur.execute(query)
        conn.commit()
