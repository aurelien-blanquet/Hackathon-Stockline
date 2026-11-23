from app.agent.guardrails import may_confirm, is_mutation
from app.schemas import ChatMessage


def msg(role, content):
    return ChatMessage(role=role, content=content)


def test_requires_recap_and_explicit_yes():
    assert not may_confirm([msg('user', 'oui')], 'voice')
    assert not may_confirm([msg('assistant', 'Votre commande : 3 kilos de tomme. Je confirme ?'), msg('user', 'non, attends')], 'voice')
    assert may_confirm([msg('assistant', 'Votre commande : 3 kilos de tomme. Je confirme ?'), msg('user', 'oui, je confirme')], 'voice')
    assert not may_confirm([msg('assistant', 'Quel est votre nom ?'), msg('user', 'oui')], 'voice')


def test_command_requires_explicit_order_confirmation():
    assert may_confirm([msg('user', 'Confirme la commande CMD-100')], 'command')
    assert not may_confirm([msg('user', 'oui')], 'command')
    assert not may_confirm([msg('user', 'Ne confirme pas la commande')], 'command')


def test_mutations_are_identified():
    assert is_mutation('create_draft_order')
    assert is_mutation('confirm_order')
    assert not is_mutation('get_price')
