import asyncio
import logging
import random
import re
from datetime import datetime
from typing import Any, Callable, List, Optional, Tuple

import discord
from discord.ext import commands

from crimsobot.bot import CrimsoBOT
from crimsobot.data.img import AENIMA, CAPTION_RULES, IMAGE_RULES, LATERALUS, URL_CONTAINS
from crimsobot.exceptions import BadCaption, NoImageFound
from crimsobot.utils import image as imagetools, tools as c

log = logging.getLogger(__name__)

eface_bucket = commands.MaxConcurrency(1, per=commands.BucketType.user, wait=False)


def shared_max_concurrency(bucket: commands.MaxConcurrency) -> Callable[[Callable], Callable]:
    def decorator(func: Callable) -> Callable:
        if isinstance(func, commands.Command):
            func._max_concurrency = bucket
        else:
            func.__commands_max_concurrency__ = bucket  # type: ignore
        return func
    return decorator


class Image(commands.Cog):
    def __init__(self, bot: CrimsoBOT):
        self.bot = bot

    async def get_previous_image(self, ctx: commands.Context) -> str:
        """A quick scrape to grab an image attachment URL from a previous message."""

        async def filename_to_check(filename: str) -> bool:
            """Check if filename is an image URL."""
            return any(x in filename for x in URL_CONTAINS)

        # grab message contents (which are strings):
        async for msg in ctx.message.channel.history(limit=IMAGE_RULES['msg_scrape_limit']):
            # if the image is an attachment (via upload)...
            if len(msg.attachments) > 0:
                attachment = msg.attachments[0]
                is_image = await filename_to_check(attachment.url)
                if is_image:
                    url = attachment.url  # type: str
                    return url
            # check for links in message...
            elif 'http' in msg.content:
                string_list = msg.content.split(' ')  # type: List[str]
                for potential_image_url in string_list:
                    is_image = await filename_to_check(potential_image_url)
                    if is_image:
                        return potential_image_url
            elif len(msg.embeds) > 0:
                embed = msg.embeds[0]
                if not embed.image.url == discord.Embed.Empty:
                    url = embed.image.url
                    return url
            else:
                continue

        raise NoImageFound

    async def get_image_and_embed(self, ctx: commands.Context, image: Optional[str], effect: str,
                                  arg: Optional[Any], title: str) -> None:
        """Get image, construct and send embed with result."""
        # process image
        fp, img_format = await imagetools.process_image(ctx, image, effect, arg)
        # if (None, None) is returned from process_image(), then the user has already been informed of issue
        if fp is None:
            return

        # filename and file
        filename = '{}{}.{}'.format(effect, datetime.utcnow().strftime('%Y%m%d%H%M%S'), img_format.lower())
        f = discord.File(fp, filename)

        embed = c.crimbed(
            title=title,
            descr=None,
            attachment=filename,
            footer='Requested by {}'.format(ctx.author),
        )

        await ctx.send(file=f, embed=embed)

    @commands.command(aliases=['acidify'])
    @commands.cooldown(2, 10, commands.BucketType.guild)
    @shared_max_concurrency(eface_bucket)
    async def acid(self, ctx: commands.Context, number_of_hits: int, image: Optional[str] = None) -> None:
        """1-3 hits only. Can use image link, attachment, mention, or emoji."""

        # exception handling
        if not 1 <= number_of_hits <= 3:
            raise commands.BadArgument('Number of hits is out of bounds.')

        if image is None:
            image = await self.get_previous_image(ctx)  # will be a URL

        effect = 'acid'
        ess = '' if number_of_hits == 1 else 's'
        title = '{}: {} hit{}'.format(effect.upper(), number_of_hits, ess)
        await self.get_image_and_embed(ctx, image, effect, number_of_hits, title)

    @commands.command(hidden=True)
    async def aenima(self, ctx: commands.Context, image: Optional[str] = None) -> None:

        effect = 'aenima'
        title = random.choice(AENIMA)

        if image is None:
            image = await self.get_previous_image(ctx)  # will be a URL

        await self.get_image_and_embed(ctx, image, effect, None, title)

    @commands.command(hidden=True)
    @commands.cooldown(1, 4 * 60 * 60, commands.BucketType.user)
    @shared_max_concurrency(eface_bucket)
    async def bless(self, ctx: commands.Context) -> None:
        """bless bless"""

        # read in lines of emojis
        line_list = open(c.clib_path_join('img', 'bless.txt'), encoding='utf8', errors='ignore').readlines()

        # strip newlines
        line_list = [line.replace('\n', '') for line in line_list]

        # send line-by-line as DM
        for line in line_list:
            await ctx.message.author.send(line)
            await asyncio.sleep(1)

    @commands.command(brief='Boop the snoot! Must mention someone to boop.')
    async def boop(self, ctx: commands.Context, mention: discord.Member) -> None:
        fp = await imagetools.make_boop_img(ctx.author.display_name, mention.display_name)

        # filename and file
        filename = '{}{}.png'.format('boop', datetime.utcnow().strftime('%Y%m%d%H%M%S'))
        f = discord.File(fp, filename)

        embed = c.crimbed(
            title='{} booped {}!'.format(ctx.author, mention),
            descr=None,
            attachment=filename,
        )

        await ctx.send(file=f, embed=embed)

    @commands.command(brief='Caption an image!')
    async def caption(self, ctx: commands.Context, *, caption_text: str, image: Optional[str] = None) -> None:
        """
        The [image] can be a link, upload, user mention (for avatar), OR an image in a previous message.

        You can add your own line breaks, eg:

        >caption You can add your own
        breaks to the text
        wherever
        you
        like! [image]
        """

        def clean_and_check(user_caption: str) -> Tuple[List[str], bool]:
            """Clean the caption and check if valid"""

            # remove superfluous spaces and trailing newlines
            cleaned_caption = re.sub(' +', ' ', user_caption).strip()

            # checks on caption
            max_length = len(cleaned_caption) < CAPTION_RULES['max_len']  # type: bool
            check = max_length

            # split by newline to preserve user input of newline
            cleaned_caption_split = cleaned_caption.split('\n')

            # clean once again
            for idx, line in enumerate(cleaned_caption_split):
                cleaned_caption_split[idx] = line.strip()

            return cleaned_caption_split, check

        async def send_to_caption_helper(caption: List[str], valid: bool) -> None:
            effect = 'caption'
            title = 'Captioned!'

            if valid:
                await self.get_image_and_embed(ctx, image, effect, caption, title)
            else:
                raise BadCaption

        # caption_text may contain a link or an emoji; if so, parse it out
        if image is None:
            try:  # first: see if there is an attachment (upload)
                image = ctx.message.attachments[0].url
            except IndexError:
                try:  # next: the last part of user_input might be a link or emoji...
                    # ...so separate the last thing in user_input and try as image input
                    image = caption_text.split(' ').pop(-1).strip()
                    caption_text_popped = caption_text.replace(image, '')
                    new_caption, valid_caption = clean_and_check(caption_text_popped)
                    await send_to_caption_helper(new_caption, valid_caption)
                    return
                except FileNotFoundError:  # returned from get_image_and_embed()
                    image = await self.get_previous_image(ctx)  # will be a URL

        new_caption, valid_caption = clean_and_check(caption_text)
        await send_to_caption_helper(new_caption, valid_caption)

    @commands.command(hidden=True)
    @commands.cooldown(1, 8 * 60 * 60, commands.BucketType.user)
    @shared_max_concurrency(eface_bucket)
    async def eface(self, ctx: commands.Context) -> None:
        """crimsoBOT avatar as emojis!"""

        # read in lines of emojis
        line_list = open(c.clib_path_join('text', 'emojiface.txt'), encoding='utf8', errors='ignore').readlines()

        # strip newlines
        line_list = [line.replace('\n', '') for line in line_list]
        for line in line_list:
            await ctx.message.author.send(line)
            await asyncio.sleep(1)

    @commands.command(hidden=True)
    @commands.is_owner()
    async def eface_pm(self, ctx: commands.Context, user: discord.User, *, message: str) -> None:
        """crimsoBOT avatar as emojis!"""

        # read in lines of emojis
        line_list = open(c.clib_path_join('text', 'emojiface.txt'), encoding='utf8', errors='ignore').readlines()

        # strip newlines
        line_list = [line.replace('\n', '') for line in line_list]
        line_list = line_list[0:-1]

        # send line-by-line as DM
        for line in line_list:
            await user.send(line)
            await asyncio.sleep(1)

        await user.send(message)

    @commands.group(aliases=['emojimage'], invoke_without_command=True)
    @commands.cooldown(1, 30, commands.BucketType.user)
    @shared_max_concurrency(eface_bucket)
    async def eimg(self, ctx: commands.Context, image: Optional[str] = None, platform: str = 'desktop') -> None:
        """
        Convert image to emojis!
        Use ">eimg mobile" or ">eimg tablet" for a smaller image.
        Works best with images with good contrast and larger features.
        """

        if image is None:
            image = await self.get_previous_image(ctx)  # will be a URL

        line_list = await imagetools.make_emoji_image(ctx, image, platform.lower().strip())

        # send line-by-line as DM
        for line in line_list:
            await ctx.message.author.send(line)
            await asyncio.sleep(0.72)

    @eimg.command(name='mobile', brief='Smallest emoji image!')
    @commands.cooldown(1, 30, commands.BucketType.user)
    @shared_max_concurrency(eface_bucket)
    async def eimg_mobile(self, ctx: commands.Context, image: Optional[str] = None) -> None:
        await self.eimg(ctx, image, platform='mobile')

    @eimg.command(name='tablet', brief='Smaller emoji image!')
    @commands.cooldown(1, 30, commands.BucketType.user)
    @shared_max_concurrency(eface_bucket)
    async def eimg_tablet(self, ctx: commands.Context, image: Optional[str] = None) -> None:
        await self.eimg(ctx, image, platform='tablet')

    @commands.command(hidden=True)
    @commands.is_owner()
    async def inspect(self, ctx: commands.Context, user: Optional[discord.User] = None) -> None:
        # read in lines of emojis
        line_list = open(c.clib_path_join('games', 'emojilist.txt'), encoding='utf8', errors='ignore').readlines()

        # strip newlines
        line_list = [line.replace('\n', '') for line in line_list]

        # send line-by-line as DM
        if not user:
            user = ctx.message.author

        for line in line_list:
            await user.send(line)
            await asyncio.sleep(1)

    @commands.command(hidden=True)
    async def lateralus(self, ctx: commands.Context, image: Optional[str] = None) -> None:

        if image is None:
            image = await self.get_previous_image(ctx)  # will be a URL

        effect = 'lateralus'
        title = random.choice(LATERALUS)
        await self.get_image_and_embed(ctx, image, effect, None, title)

    @commands.command()
    async def needban(self, ctx: commands.Context, image: Optional[str] = None) -> None:
        """SOMEONE needs BAN. User mention, attachment, link, or emoji."""

        if image is None:
            image = await self.get_previous_image(ctx)  # will be a URL

        effect = 'needban'
        title = 'Need ban?'
        await self.get_image_and_embed(ctx, image, effect, None, title)

    @commands.command()
    async def needping(self, ctx: commands.Context, image: Optional[str] = None) -> None:
        """SOMEONE needs PING. User mention, attachment, link, or emoji."""

        if image is None:
            image = await self.get_previous_image(ctx)  # will be a URL

        effect = 'needping'
        title = 'Need ping?'
        await self.get_image_and_embed(ctx, image, effect, None, title)

    @commands.command(aliases=['verpingt'])
    async def pingbadge(self, ctx: commands.Context, image: Optional[str] = None) -> None:
        """Add Discord notification badge to an image."""

        if image is None:
            image = await self.get_previous_image(ctx)  # will be a URL

        embed = c.crimbed(
            title='Choose a corner:',
            descr='\n'.join([
                '1. Top left',
                '2. Top right',
                '3. Bottom left',
                '4. Bottom right',
            ]),
            thumb_name='https://i.imgur.com/cgGKghX.png',
        )
        prompt = await ctx.send(embed=embed)

        # define check for position vote
        def check(msg: discord.Message) -> bool:
            try:
                valid_choice = 0 < int(msg.content) <= 4
                in_channel = msg.channel == ctx.message.channel
                is_author = msg.author == ctx.message.author
                return valid_choice and in_channel and is_author
            except ValueError:
                return False

        # define default position, listen for user to specify different one
        msg = await self.bot.wait_for('message', check=check, timeout=15)
        if msg is None:
            position = 4
        else:
            position = int(msg.content)

        # delete prompt and vote, send image
        if msg is not None:
            await msg.delete()
        await prompt.delete()

        effect = 'pingbadge'
        title = 'verpingt!'
        await self.get_image_and_embed(ctx, image, effect, position, title)

    @commands.command()
    async def xokked(self, ctx: commands.Context, image: Optional[str] = None) -> None:
        """Get xokked! User mention, attachment, link, or emoji."""

        if image is None:
            image = await self.get_previous_image(ctx)  # will be a URL

        effect = 'xokked'
        title = '<:xok:563825728102334465>'
        await self.get_image_and_embed(ctx, image, effect, None, title)


def setup(bot: CrimsoBOT) -> None:
    bot.add_cog(Image(bot))
