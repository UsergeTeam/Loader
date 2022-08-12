from importlib import import_module
from os import execl
from sys import executable


if __name__ == '__main__':
    try:
        getattr(import_module("loader.core.main"), 'load')()
    except InterruptedError:
        execl(executable, executable, '-m', 'loader')
        raise SystemExit
# pylint: disable=missing-module-docstring
#
# Copyright (C) 2020-2022 by alexaTeam@Github, < https://github.com/alexaTeam >.
#
# This file is part of < https://github.com/alexaTeam/alexa > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/alexaTeam/alexa/blob/master/LICENSE >
#
# All rights reserved.

from telethon.tl.functions.messages import (GetHistoryRequest)
from telethon.tl.types import (
PeerChannel
)

offset_id = 0
limit = 100
all_messages = []
total_messages = 0
total_count_limit = 0

while True:
    print("Current Offset ID is:", offset_id, "; Total Messages:", total_messages)
    history = client(GetHistoryRequest(
        peer=my_channel,
        offset_id=offset_id,
        offset_date=None,
        add_offset=0,
        limit=limit,
        max_id=0,
        min_id=0,
        hash=0
    ))
    if not history.messages:
        break
    messages = history.messages
    for message in messages:
        all_messages.append(message.to_dict())
    offset_id = messages[len(messages) - 1].id
    total_messages = len(all_messages)
    if total_count_limit != 0 and total_messages >= total_count_limit:
        break