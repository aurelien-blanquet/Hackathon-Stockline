"""The written recap sent to the customer the moment the order is confirmed (tools/orders.py)."""

from app.tools.orders import recap_channel, recap_text

ORDER = {
    "number": "CMD-2026-006832", "deliveryDate": "2026-11-28", "totalHt": 1240.0,
    "client": {"name": "Le Panier Savoyard", "contacts": [{"name": "Jean-Marc Dupraz", "role": "Gérant", "phone": "06 99 90 91 85"}]},
    "lines": [{"qty": 10, "unit": "kg", "productName": "Diots de Savoie nature (barquette 1 kg)"},
              {"qty": 6, "unit": "kg", "productName": "Raclette de Savoie IGP tranchée (barquette 1 kg)"}],
}


def test_the_recap_is_short_and_says_what_matters():
    text = recap_text(ORDER, "2026-11-24")
    assert text.startswith("Crèmerie des Aravis — commande 6832 confirmée : 10 kg Diots de Savoie nature · 6 kg Raclette")
    assert "Livraison samedi 28/11." in text and "Total 1 240,00 € HT." in text and text.endswith("Merci Jean-Marc !")
    assert "CMD-" not in text and "(barquette" not in text and len(text) < 260


def test_a_long_order_is_summarised():
    many = {**ORDER, "lines": [{"qty": i + 1, "unit": "kg", "productName": f"Produit {i}"} for i in range(7)]}
    assert "+ 3 autres produits" in recap_text(many, "2026-11-24")


def test_the_recap_goes_to_whoever_places_the_orders_on_their_channel():
    chalet = {"name": "Le Chalet de la Balme", "preferences": "Commande par WhatsApp la veille.",
              "contacts": [{"name": "Raymond Thovex", "role": "Patron", "phone": "06 07"}, {"name": "Mélanie Thovex", "role": "Fille, gère les commandes", "phone": "06 41"}]}  # fmt: skip
    assert recap_channel(chalet) == ("whatsapp", "Mélanie Thovex · 06 41")
    assert recap_channel(ORDER["client"]) == ("sms", "Jean-Marc Dupraz · 06 99 90 91 85")
    assert recap_channel({"name": "X", "contacts": [{"name": "Paul", "email": "p@x.fr"}]})[0] == "email"
    assert recap_channel({"name": "X", "contacts": []}) is None  # nobody to send it to: nothing is sent
