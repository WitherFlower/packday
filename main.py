# This example requires the 'message_content' intent.

import os
import re

import discord
import psycopg2
from discord.ext import commands
from dotenv import load_dotenv
from ossapi import Ossapi, UserLookupKey

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PASSWORD = os.getenv("DB_PASSWORD")

CURRENT_PACK_ID = os.getenv("CURRENT_PACK")

# Bot Setup

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='>p ', intents=intents)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

# DB Setup

conn = psycopg2.connect(
    host="localhost",
    database="unpack",
    user="postgres",
    password=DB_PASSWORD
)


# ossapi setup

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

api = Ossapi(CLIENT_ID, CLIENT_SECRET)  # type: ignore

# Bot Commands

# Score Commands


@bot.command()
async def register(ctx: commands.Context, arg: str):

    if not re.match("[1-9][0-9]*", arg):
        await ctx.send('Error : Invalid user ID')
        return

    osu_user_name = api.user(arg, key=UserLookupKey.ID).username

    query = f"""
    INSERT INTO registered_users (discord_id, osu_user_id, osu_user_name) VALUES ({ctx.author.id}, {arg}, '{osu_user_name}')
    ON CONFLICT (discord_id) DO UPDATE SET
        osu_user_id = excluded.osu_user_id,
        osu_user_name = excluded.osu_user_name;
    """
    with conn.cursor() as cur:
        cur.execute(query)
        conn.commit()

    await ctx.send(f"Registered user {ctx.author.name} with osu! id {arg} and username {osu_user_name}")


@bot.command(aliases=['lb'])
async def leaderboard(ctx: commands.Context, arg: str):
    pack_id = 0
    try:
        pack_id = int(arg)
    except ValueError:
        await ctx.send("Error : Invalid pack ID")
        return

    query = f"""
    SELECT osu_user_id, osu_user_name, total_score FROM 
        (SELECT user_id, SUM(score) as total_score FROM scores WHERE pack_id={pack_id} GROUP BY user_id) 
        as total_score_table
    JOIN registered_users ON total_score_table.user_id = registered_users.osu_user_id ORDER BY total_score DESC;"""

    result = list()

    with conn.cursor() as cur:
        cur.execute(query)
        result = cur.fetchall()

    if len(result) == 0:
        await ctx.send("No Result")
        return

    embed = discord.Embed(title=f"Score Leaderboard for Pack #{pack_id}")

    lb_string = "```css\n"
    for index, row in enumerate(result):

        rank = "#" + "{:<2}".format(index+1)
        username = "{:15}".format(row[1])
        thousand_separated_total_score = "{:,}".format(int(row[2]))
        total_score = "{:>15}".format(thousand_separated_total_score)

        row_string = f"{rank}| {username}|{total_score}\n"
        lb_string += row_string

    lb_string += "```"

    embed.description = lb_string

    await ctx.send(embed=embed)

# Help


@bot.command()
async def show_help(ctx: commands.Context):
    embed = discord.Embed(title="Available Commands")

    utility_field = """
    `>p show_help` : Shows this message
    `>p register <osu_user_id>` : Register as the user with the given id
    `>p leaderboard <pack_id>` : View leaderboard for a given pack (alias : `>p lb <pack_id>`)
    """
    embed.add_field(name="Utility Commands", value=utility_field)

    fun_content = """
    `>p barack` : We're Barack.
    `>p ????` : ????
    """
    embed.add_field(name="Fun", value=fun_content)

    await ctx.send(embed=embed)


# Fun

@bot.command()
async def meow(ctx: commands.Context):
    await ctx.send("https://cdn.discordapp.com/emojis/1086007780957241364.gif?size=128&quality=lossless")


@bot.command()
async def barack(ctx: commands.Context):
    await ctx.send("https://cdn.discordapp.com/attachments/750265305258786870/1133087258149392634/FzuaWTAaMAIjL5Z.png")


@bot.command()
async def thevoices(ctx: commands.Context):
    await ctx.send("<a:TheVoices:1147890732322009199>")


bot.run(BOT_TOKEN)  # type: ignore
