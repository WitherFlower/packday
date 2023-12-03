import logging
import os
from datetime import datetime, timedelta
import sys
import time
import traceback
from typing import List

import psycopg2
from dotenv import load_dotenv
from ossapi import Beatmap, Ossapi, Score, ScoreType
from timeloop import Timeloop

from discord import Webhook
import aiohttp
import asyncio
import backoff

load_dotenv()


# ossapi setup


CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

PACK_START_TIME = datetime.fromisoformat(
    os.getenv("PACK_START_TIME"))  # type: ignore
PACK_END_TIME = datetime.fromisoformat(
    os.getenv("PACK_END_TIME"))  # type: ignore

api = Ossapi(CLIENT_ID, CLIENT_SECRET)  # type: ignore


# DB Setup


DB_PASSWORD = os.getenv("DB_PASSWORD")

conn = psycopg2.connect(
    host="localhost",
    database="unpack",
    user="postgres",
    password=DB_PASSWORD
)

CURRENT_PACK_ID = os.getenv("CURRENT_PACK")

WEBHOOK_URL = os.getenv("WEBHOOK_URL")


# DB Calls


def get_current_pack_maps():

    query = f"SELECT beatmap_id FROM maps WHERE pack_id={CURRENT_PACK_ID}"

    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()


def get_map_mods(pack_id: int, map_id: int) -> tuple[list[str], float, bool] | None:

    query = f"SELECT mods, multiplier, exact_mods FROM maps WHERE beatmap_id={map_id} and pack_id={pack_id}"

    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchone()  # type: ignore


def update_score_in_db(score: Score):

    if score.beatmap is None:
        return

    get_score_query = f"SELECT score FROM scores WHERE user_id={score.user_id} AND beatmap_id={score.beatmap.id} AND pack_id={CURRENT_PACK_ID}"

    map_mod_data = get_map_mods(int(CURRENT_PACK_ID), score.beatmap.id)  # type: ignore

    if map_mod_data != None:
        mods, multiplier, exact = map_mod_data

        if mods != None:

            score_mods = score.mods.decompose()

            score_has_all_mods = True

            for mod in score_mods:
                score_has_all_mods &= (mod.short_name() in mods)

            score_exact_mods = score_has_all_mods and (len(score_mods) == len(mods))

            if exact and score_exact_mods:
                score.score = round(score.score * multiplier)
            elif score_has_all_mods and not exact:
                score.score = round(score.score * multiplier)

    with conn.cursor() as cur:
        cur.execute(get_score_query)
        result = cur.fetchone()

        # If a score for this (user_id, beatmap_id) already exists,
        # only update it if the score is higher
        if result is not None and result[0] >= score.score:
            print(
                f"Score was found in db but incoming score is lower ({score.score} <= {result[0]})")
            return

        old_score: int = result[0] if result is not None else 0

    # Here, the score either doesn't exit or a better socre has been set

    update_query = f"""
    INSERT INTO scores (user_id, beatmap_id, pack_id, score_id, score, combo, accuracy, rank)
    VALUES ({score.user_id}, {score.beatmap.id}, {CURRENT_PACK_ID}, {score.id}, {score.score}, {score.max_combo}, {score.accuracy}, '{score.rank.name}')
    ON CONFLICT (user_id, beatmap_id, pack_id) DO UPDATE SET
        score_id = excluded.score_id,
        score = excluded.score,
        combo = excluded.combo,
        accuracy = excluded.accuracy,
        rank = excluded.rank;
    """

    with conn.cursor() as cur:
        cur.execute(update_query)
        conn.commit()
        print(f'''
            Score was updated in db - New High Score : 
            {score.score} Score | {score.max_combo}x | {round(score.accuracy*100, 2)}%
            ''')

    asyncio.run(
        send_new_score(score.user().username, score.beatmap,
                       old_score, score.score)
    )


# Discord Webhook Stuff


async def send_new_score(username: str, beatmap: Beatmap, old_score: int, new_score: int):
    async with aiohttp.ClientSession() as session:
        webhook = Webhook.from_url(
            WEBHOOK_URL, session=session)  # type: ignore

        beatmapset = beatmap.beatmapset()
        map_string = f'{beatmapset.artist} - {beatmapset.title} [{beatmap.version}]'

        score_diff = new_score - old_score
        thousand_separated_score_diff = "{:,}".format(score_diff)

        await webhook.send(f'''
New score found for {username} on {map_string} :
{thousand_separated_score_diff} Score Gained <:SCOER:1097492109432463440>
''')


async def found_new_score(score: Score):
    async with aiohttp.ClientSession() as session:
        webhook = Webhook.from_url(
            WEBHOOK_URL, session=session)  # type: ignore

        map_id = score.beatmap.id if score.beatmap is not None else 0

        await webhook.send(f'''
Checking score for user {score.user_id} on map {map_id}
''')


def notify_error(details):
    async def inner():
        async with aiohttp.ClientSession() as session:
            webhook = Webhook.from_url(
                WEBHOOK_URL, session=session)  # type: ignore

            await webhook.send('Shit hit the fan')
    asyncio.run(inner())

    exc_type, exc_value, exc_traceback = sys.exc_info()
    traceback.print_tb(exc_traceback)
    traceback.print_exception(exc_type, exc_value, exc_traceback)


# Periodic Task setup


tl = Timeloop()

logging.getLogger('backoff').addHandler(logging.StreamHandler())


@backoff.on_exception(backoff.expo, Exception, on_backoff=notify_error, max_tries=5)  # type: ignore
def update_scores_in_db(user_id: int):

    current_pack_maps: List[int] = list(map(lambda tuple_id: tuple_id[0], get_current_pack_maps()))

    recent_scores: List[Score] = api.user_scores(user_id, ScoreType.RECENT, limit=100, include_fails=False)

    for score in recent_scores:

        beatmap = score.beatmap

        if beatmap is None:
            return

        if score.created_at < PACK_START_TIME or score.created_at > PACK_END_TIME:
            continue

        if current_pack_maps.__contains__(beatmap.id):
            print(f"Recent score found on map {beatmap.id}, checking db for update...")
            # asyncio.run(
            #     found_new_score(score)
            # )
            update_score_in_db(score)


@tl.job(interval=timedelta(minutes=15))
def update_all_registered_users():

    get_users_query = "SELECT osu_user_id FROM registered_users"

    users = list()

    with conn.cursor() as cur:
        cur.execute(get_users_query)
        users = cur.fetchall()

    for (user,) in users:
        print(f"Fetching scores for user {user}...")
        update_scores_in_db(user)

        print("Sleeping for API...")
        time.sleep(5)


update_all_registered_users()
tl.start(block=True)
