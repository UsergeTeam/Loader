# pylint: disable=invalid-name, missing-module-docstring
#
# Copyright (C) 2020-2022 by alexaTeam@Github, < https://github.com/alexaTeam >.
#
# This file is part of < https://github.com/alexaTeam/alexa > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/alexaTeam/alexa/blob/master/LICENSE >
#
# All rights reserved.

import asyncio
import os

from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.errors import UserIsBot

if os.path.isfile("config.env"):
    load_dotenv("config.env")


async def string() -> None:  # pylint: disable=missing-function-docstring
    async with Client(
        "alexa",
        api_id=int(os.environ.get("API_ID") or input("Enter Telegram APP ID: ")),
        api_hash=os.environ.get("API_HASH") or input("Enter Telegram API HASH: "),
    ) as alexa:
        print("\nprocessing...")
        out = "sent to saved messages!"
        try:
            await alexa.send_message(
                "me", f"#alexa #SESSION_STRING\n\n`{await alexa.export_session_string()}`"
            )
        except UserIsBot:
            out = "successfully printed!"
            print(await alexa.export_session_string())
        print(f"Done !, session string has been {out}")


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(string())
