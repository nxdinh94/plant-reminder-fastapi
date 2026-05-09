from types import SimpleNamespace

from app.services.agent_chat import LangGraphChatAgent


class _StubGraph:
    def __init__(self, has_interrupt: bool) -> None:
        self.has_interrupt = has_interrupt

    def get_state(self, _config):  # noqa: ANN001
        interrupts = ("pending",) if self.has_interrupt else ()
        return SimpleNamespace(interrupts=interrupts)


def test_thread_has_pending_interrupt_true() -> None:
    agent = LangGraphChatAgent()
    agent._graph = _StubGraph(has_interrupt=True)
    config = {"configurable": {"thread_id": "t1"}}
    assert agent._thread_has_pending_interrupt(config) is True


def test_thread_has_pending_interrupt_false() -> None:
    agent = LangGraphChatAgent()
    agent._graph = _StubGraph(has_interrupt=False)
    config = {"configurable": {"thread_id": "t1"}}
    assert agent._thread_has_pending_interrupt(config) is False

