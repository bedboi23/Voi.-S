import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv
import time

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

queues = {}
now_playing = {}

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown Track')
        self.duration = data.get('duration', 180)
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader', 'Unknown Artist')

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

def create_progress_bar(current, total, length=20):
    if total == 0:
        return "🔵" + "─" * (length - 1)
    percent = min(current / total * length, length)
    filled = int(percent)
    bar = "─" * filled + "🔵" + "─" * (length - filled - 1)
    return bar

def format_time(seconds):
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"

def create_now_playing_embed(player, current_pos, total_duration):
    bar = create_progress_bar(current_pos, total_duration)
    current_time = format_time(current_pos)
    total_time = format_time(total_duration)

    embed = discord.Embed(title="**Now Playing**", color=0x5865F2)

    embed.add_field(
        name="**Track info**",
        value=(
            f"**{player.title[:45]}**\n"
            f"🎨 Artist: **{player.uploader[:20]}**\n"
            f"⏱️ {current_time} / {total_time}"
        ),
        inline=True
    )

    embed.add_field(
        name="**Status**",
        value="**▶️ Currently streaming in voice channel**",
        inline=True
    )

    embed.description = (
        f"**{player.title[:50]}**\n"
        f"`{bar}` {current_time} / {total_time}"
    )

    if player.thumbnail:
        embed.set_thumbnail(url=player.thumbnail)

    embed.set_footer(text="spotify • Yukihana")

    return embed

@bot.event
async def on_ready():
    print(f'{bot.user} is online!')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} commands')
    except Exception as e:
        print(f'Sync error: {e}')

@bot.tree.command(name="play", description="Play a song from YouTube")
@app_commands.describe(query="Song name or YouTube URL")
async def play(interaction: discord.Interaction, query: str):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ Join a voice channel first!", ephemeral=True)
        return

    await interaction.response.defer()

    try:
        channel = interaction.user.voice.channel
        if not interaction.guild.voice_client:
            vc = await channel.connect()
        else:
            vc = interaction.guild.voice_client

        if interaction.guild.id not in queues:
            queues[interaction.guild.id] = []

        search_query = f"ytsearch1:{query}" if not query.startswith(('http', 'https')) else query

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=False))

        if 'entries' in data:
            data = data['entries'][0]

        player = YTDLSource(
            discord.FFmpegPCMAudio(data['url'], **ffmpeg_options),
            data=data
        )

        queues[interaction.guild.id].append(player)

        embed = create_now_playing_embed(player, 0, player.duration)
        message = await interaction.followup.send(embed=embed)

        now_playing[interaction.guild.id] = {
            'message': message,
            'player': player,
            'start_time': time.time()
        }

        if not vc.is_playing():
            await play_next(interaction.guild)

    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

async def play_next(guild):
    if guild.id not in queues or not queues[guild.id]:
        return

    vc = guild.voice_client
    if not vc:
        return

    player = queues[guild.id].pop(0)

    def after_playing(error):
        if error:
            print(f'Playback error: {error}')
        if guild.id in queues and queues[guild.id]:
            asyncio.create_task(play_next(guild))
        else:
            now_playing.pop(guild.id, None)

    vc.play(player, after=after_playing)

    if guild.id in now_playing:
        now_playing[guild.id]['player'] = player
        now_playing[guild.id]['start_time'] = time.time()
        asyncio.create_task(animate_progress(guild, player))

async def animate_progress(guild, player):
    if guild.id not in now_playing:
        return

    try:
        msg = now_playing[guild.id]['message']
        start_time = now_playing[guild.id]['start_time']

        while guild.voice_client and guild.voice_client.is_playing():
            elapsed = time.time() - start_time
            current_pos = min(elapsed, player.duration)

            embed = create_now_playing_embed(player, current_pos, player.duration)
            await msg.edit(embed=embed)
            await asyncio.sleep(2)
    except:
        pass

@bot.tree.command(name="pause", description="Pause music")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸️ Paused", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Nothing playing", ephemeral=True)

@bot.tree.command(name="resume", description="Resume music")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Resumed", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Not paused", ephemeral=True)

@bot.tree.command(name="skip", description="Skip current song")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await interaction.response.send_message("⏭️ Skipped", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Nothing playing", ephemeral=True)

@bot.tree.command(name="stop", description="Stop music and disconnect")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        queues[interaction.guild.id] = []
        now_playing.pop(interaction.guild.id, None)
        await vc.disconnect()
        await interaction.response.send_message("⏹️ Stopped and disconnected", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Not in voice channel", ephemeral=True)

@bot.tree.command(name="queue", description="Show current queue")
async def queue_cmd(interaction: discord.Interaction):
    if interaction.guild.id not in queues or not queues[interaction.guild.id]:
        await interaction.response.send_message("📭 Queue is empty", ephemeral=True)
        return

    songs = [f"{i+1}. **{song.title[:30]}**" for i, song in enumerate(queues[interaction.guild.id])]

    embed = discord.Embed(
        title="📋 Song Queue",
        description="\n".join(songs),
        color=0x5865F2
    )

    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)