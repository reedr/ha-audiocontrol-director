"""A fake AudioControl Director, seeded from captured amplifier replies."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

_CMD = re.compile(
    r"^(Z\d+|GRP\d+|DXO[ab])"
    r"(on|off|setvol(\d+)|source(MX\d+|DX[a-d])|setbass(-?\d+)|settreble(-?\d+)"
    r"|eq([1-6])|loudness([01])|signalsense([01]))$"
)
EQ_NAMES = {0: "Acoustic", 2: "Party", 3: "User 1", 5: "User 3"}


class FakeDirector:
    """Serves the telnet protocol for one amplifier on 127.0.0.1."""

    def __init__(self, amp: str = "amp98") -> None:
        """Load the amplifier's captured status."""
        self.inputs = (FIXTURES / f"{amp}_INPUT.txt").read_text().replace("\n", "\r\n")
        self.inputs = self.inputs.replace("\r\r\n", "\r\n")
        status = (FIXTURES / f"{amp}_SYSTEMstat.txt").read_text().replace("\r", "")
        head, table = status.split("\n\n", 1)
        self.header = head.splitlines()
        self.name = self.header[0].split(": ", 1)[1]
        self.analog = sum(1 for line in self.inputs.splitlines() if line.startswith("Channel"))
        self.digital = [
            chr(ord("a") + i)
            for i in range(
                sum(1 for line in self.inputs.splitlines() if line.startswith("Digital In"))
            )
        ]
        self.outputs: list[dict] = []
        for line in table.splitlines()[1:]:
            f = [x.strip() for x in line.split(",")]
            eq_name, eq_idx = f[7].rsplit(" and ", 1)
            self.outputs.append(
                {
                    "name": f[0],
                    "on": f[2] == "on",
                    "src": int(f[3].split()[0][2:]),
                    "vol": int(f[4]),
                    "bass": int(f[5]),
                    "treble": int(f[6]),
                    "eq": int(eq_idx),
                    "eq_name": eq_name,
                    "group": int(f[8]),
                    "temp": f[9],
                    "sense": f[10] == "on",
                    "loud": False,
                }
            )
        self.shorts = [0] * len(self.zones)
        self.commands: list[str] = []
        self.silent = False
        # Seconds to stall before each status row, as a busy amplifier might.
        self.row_pause = 0.0
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self.port = 0

    @property
    def zones(self) -> list[dict]:
        return [o for o in self.outputs if not o["name"].startswith("Digital Out")]

    def _targets(self, target: str) -> list[dict]:
        if target.startswith("GRP"):
            return [z for z in self.zones if z["group"] == int(target[3:])]
        if target.startswith("DXO"):
            digital = [o for o in self.outputs if o["name"].startswith("Digital Out")]
            return [digital[ord(target[3]) - ord("a")]]
        return [self.outputs[int(target[1:]) - 1]]

    def systemstat(self) -> str:
        rows = [
            ", ".join(
                [
                    o["name"],
                    str(i + 1),
                    "on" if o["on"] else "off",
                    f"MX{o['src']} & {o['src']}",
                    str(o["vol"]),
                    str(o["bass"]),
                    str(o["treble"]),
                    f"{EQ_NAMES.get(o['eq'], 'unsaved values') if o['eq'] >= 0 else 'unsaved values'} and {o['eq']}",
                    str(o["group"]),
                    o["temp"],
                    "on" if o["sense"] else "off",
                ]
            )
            for i, o in enumerate(self.outputs)
        ]
        header = "ZONES, #, POWER STATE, INPUT, VOLUME, BASS, TREBLE, EQ, GROUP, TEMP, SIG. SENSE"
        return "\r\n".join([*self.header, "", header, *rows]) + "\r\n"

    def reply(self, cmd: str) -> str:
        """The body after the echo."""
        if cmd == "SYSTEMstat?":
            return self.systemstat()
        if cmd == "INPUT?":
            return self.inputs
        if cmd == "AMP?":
            return self.name
        if cmd == "PROTECT?":
            return "Normal\r\n"
        if cmd == "SHORT?":
            return " ".join(str(s) for s in self.shorts) + " \r\n"
        if m := re.fullmatch(r"Z(\d+)loudness\?", cmd):
            return ("On" if self.outputs[int(m[1]) - 1]["loud"] else "Off") + "\r\n"
        if cmd in ("allZon", "allZoff"):
            for o in self.outputs:
                o["on"] = cmd == "allZon"
            return f"01{cmd}\r\n"
        if cmd in ("power1", "power0"):
            return f"01{cmd}\r\n"
        m = _CMD.match(cmd)
        if not m:
            return f"xx{cmd}xx\r\n"
        verb = m[2]
        for o in self._targets(m[1]):
            if verb in ("on", "off"):
                o["on"] = verb == "on"
            elif m[3] is not None:
                o["vol"] = int(m[3])
            elif m[4] is not None:
                code = m[4]
                o["src"] = (
                    int(code[2:])
                    if code.startswith("MX")
                    else self.analog + self.digital.index(code[2]) + 1
                )
            elif m[5] is not None:
                o["bass"] = int(m[5])
            elif m[6] is not None:
                o["treble"] = int(m[6])
            elif m[7] is not None:
                o["eq"] = int(m[7]) - 1
            elif m[8] is not None:
                o["loud"] = m[8] == "1"
            elif m[9] is not None:
                o["sense"] = m[9] == "1"
        return f"01{cmd}\r\n"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.append(writer)
        buf = b""
        try:
            while data := await reader.read(1024):
                buf += data
                while b"\r" in buf:
                    line, buf = buf.split(b"\r", 1)
                    cmd = line.decode().strip()
                    if not cmd:
                        continue
                    self.commands.append(cmd)
                    if self.silent:
                        continue
                    reply = f"{cmd}\r{self.reply(cmd)}"
                    if cmd == "SYSTEMstat?" and self.row_pause:
                        for part in reply.split("\r\n"):
                            writer.write(f"{part}\r\n".encode())
                            await writer.drain()
                            await asyncio.sleep(self.row_pause)
                        continue
                    writer.write(reply.encode())
                    await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    def drop_sessions(self) -> None:
        """End every session, as the amplifier does after four hours."""
        for writer in self._writers:
            writer.close()
        self._writers.clear()

    async def stop(self) -> None:
        self.drop_sessions()
        if self._server:
            self._server.close()
            self._server.close_clients()
            await self._server.wait_closed()
