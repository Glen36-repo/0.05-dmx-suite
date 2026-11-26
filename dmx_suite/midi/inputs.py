"""MIDI input ports. Real ports need python-rtmidi (Windows wheels); the simulator uses FakeMidiIn."""

from __future__ import annotations

from typing import Any, Callable

Handler = Callable[[Any, str], Any]  # (mido message, port name)


def port_names() -> list[str]:
    import mido

    return list(mido.get_input_names())


class MidiInputs:
    """Opens real ports with callbacks, so a drum hit is handled on arrival (no polling)."""

    def __init__(self, names: list[str] | None, handler: Handler) -> None:
        import mido

        wanted = names or port_names()
        self.ports = []
        for name in wanted:
            self.ports.append(mido.open_input(name, callback=lambda msg, n=name: handler(msg, n)))

    def close(self) -> None:
        for p in self.ports:
            p.close()


class FakeMidiIn:
    """Simulator input: inject messages as if they came from a port."""

    def __init__(self, handler: Handler, name: str = "sim") -> None:
        import mido  # noqa: F401  load now so the first simulated hit isn't slowed by the import

        self.handler = handler
        self.name = name

    def note(self, note: int, velocity: int = 100, channel: int = 10) -> Any:
        import mido

        return self.handler(mido.Message("note_on", channel=channel - 1, note=note, velocity=velocity), self.name)

    def note_off(self, note: int, channel: int = 10) -> Any:
        import mido

        return self.handler(mido.Message("note_off", channel=channel - 1, note=note, velocity=0), self.name)

    def program(self, program: int, channel: int = 1) -> Any:
        import mido

        return self.handler(mido.Message("program_change", channel=channel - 1, program=program), self.name)

    def cc(self, control: int, value: int, channel: int = 1) -> Any:
        import mido

        return self.handler(mido.Message("control_change", channel=channel - 1, control=control, value=value), self.name)

    def close(self) -> None:
        pass
