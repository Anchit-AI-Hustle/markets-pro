"""Broker linking: what gets sent, what comes back, and what is refused."""

import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

from autotrader.broker import relay
from autotrader.broker.providers import PROVIDERS, Holding, available, linkable

KEY, SECRET = "testkey", "testsecret"
REDIRECT = "https://markets-pro.anchit-tandon.com/api/broker/callback"


class ZerodhaTest(unittest.TestCase):
    provider = PROVIDERS["kite"]

    def test_login_goes_to_zerodha_not_to_us(self):
        url = self.provider.authorize(KEY, REDIRECT, "st")
        self.assertTrue(url.startswith("https://kite.zerodha.com/connect/login"))
        self.assertIn("api_key=testkey", url)

    def test_no_secret_is_ever_put_in_the_login_url(self):
        # It would be in the reader's address bar and their browser history.
        self.assertNotIn(SECRET, self.provider.authorize(KEY, REDIRECT, "st"))

    def test_exchange_checksum_is_sha256_of_the_three_values(self):
        request = self.provider.exchange(KEY, SECRET, {"request_token": "rt"}, REDIRECT)
        expected = hashlib.sha256((KEY + "rt" + SECRET).encode()).hexdigest()
        self.assertEqual(request.body["checksum"], expected)
        self.assertEqual(request.url, "https://api.kite.trade/session/token")
        self.assertTrue(request.form)

    def test_exchange_does_not_send_the_secret_itself(self):
        # Zerodha authenticates by checksum; sending the secret as well would
        # put it on the wire for no reason.
        request = self.provider.exchange(KEY, SECRET, {"request_token": "rt"}, REDIRECT)
        self.assertNotIn(SECRET, str(request.body))

    def test_holdings_are_read_with_the_token_header(self):
        request = self.provider.holdings(KEY, "tok")
        self.assertEqual(request.headers["Authorization"], "token testkey:tok")

    def test_parses_a_holdings_payload(self):
        rows = self.provider.parse_holdings({"data": [
            {"tradingsymbol": "RELIANCE", "exchange": "NSE", "quantity": 10,
             "average_price": "2400.5", "last_price": "2500"},
        ]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].symbol, "RELIANCE")
        self.assertEqual(rows[0].value, Decimal("25000"))
        self.assertEqual(rows[0].pnl, Decimal("995.0"))

    def test_order_is_a_delivery_market_order(self):
        request = self.provider.order(KEY, "tok", "TCS", 3, "buy", "NSE")
        self.assertEqual(request.body["transaction_type"], "BUY")
        self.assertEqual(request.body["order_type"], "MARKET")
        self.assertEqual(request.body["product"], "CNC")


class UpstoxTest(unittest.TestCase):
    provider = PROVIDERS["upstox"]

    def test_authorize_is_standard_oauth(self):
        url = self.provider.authorize(KEY, REDIRECT, "st")
        self.assertIn("response_type=code", url)
        self.assertIn("client_id=testkey", url)
        self.assertIn("state=st", url)

    def test_exchange_posts_the_authorization_code(self):
        request = self.provider.exchange(KEY, SECRET, {"code": "abc"}, REDIRECT)
        self.assertEqual(request.body["grant_type"], "authorization_code")
        self.assertEqual(request.body["code"], "abc")

    def test_parses_a_holdings_payload(self):
        rows = self.provider.parse_holdings({"data": [
            {"tradingsymbol": "INFY", "quantity": 5,
             "average_price": 1400, "last_price": 1500},
        ]})
        self.assertEqual(rows[0].pnl, Decimal("500"))


class AngelOneTest(unittest.TestCase):
    provider = PROVIDERS["angelone"]

    def test_uses_the_publisher_redirect_not_the_password_login(self):
        # SmartAPI's other login takes a client code, PIN and TOTP directly.
        # Sending a reader's PIN through this app is not something to do.
        url = self.provider.authorize(KEY, REDIRECT, "st")
        self.assertTrue(url.startswith("https://smartapi.angelone.in/publisher-login"))

    def test_token_arrives_in_the_redirect_with_no_exchange(self):
        self.assertFalse(self.provider.exchanges_token)
        token = self.provider.token_from_redirect(
            {"auth_token": "jwt", "client_code": "A123"})
        self.assertEqual(token["access_token"], "jwt")
        self.assertEqual(token["account"], "A123")

    def test_holdings_carry_the_private_key_header(self):
        request = self.provider.holdings(KEY, "tok")
        self.assertEqual(request.headers["X-PrivateKey"], KEY)

    def test_parses_both_payload_shapes(self):
        row = {"tradingsymbol": "SBIN", "quantity": 2, "averageprice": 500, "ltp": 550}
        nested = self.provider.parse_holdings({"data": {"holdings": [row]}})
        flat = self.provider.parse_holdings({"data": [row]})
        self.assertEqual(nested[0].pnl, flat[0].pnl, Decimal("100"))


class AlpacaTest(unittest.TestCase):
    provider = PROVIDERS["alpaca"]

    def test_is_armed_by_the_deployment_not_by_a_login(self):
        self.assertNotIn(self.provider, linkable())

    def test_parses_a_positions_list(self):
        rows = self.provider.parse_holdings([
            {"symbol": "AAPL", "qty": "4", "avg_entry_price": "180",
             "current_price": "190"},
        ])
        self.assertEqual(rows[0].pnl, Decimal("40"))
        self.assertEqual(rows[0].currency, "USD")


class MalformedPayloadTest(unittest.TestCase):
    """A broker's bad field must not cost the reader the whole portfolio."""

    def test_missing_numbers_become_zero_not_an_exception(self):
        rows = PROVIDERS["kite"].parse_holdings({"data": [
            {"tradingsymbol": "X", "quantity": None, "average_price": "",
             "last_price": "not a number"},
        ]})
        self.assertEqual(rows[0].quantity, Decimal("0"))
        self.assertEqual(rows[0].last_price, Decimal("0"))

    def test_absent_data_key_yields_nothing(self):
        for name in ("kite", "upstox", "angelone"):
            self.assertEqual(PROVIDERS[name].parse_holdings({}), [])


class StateTest(unittest.TestCase):
    """The callback is an unauthenticated GET; the signature is the whole defence."""

    def test_round_trips(self):
        state = relay.sign_state("user-1", "kite", "s3cret")
        self.assertEqual(relay.verify_state(state, "s3cret"), ("user-1", "kite"))

    def test_a_tampered_payload_is_refused(self):
        state = relay.sign_state("user-1", "kite", "s3cret")
        forged = relay.sign_state("attacker", "kite", "s3cret").split(".")[0] \
            + "." + state.split(".")[1]
        with self.assertRaises(relay.RelayError):
            relay.verify_state(forged, "s3cret")

    def test_another_deployments_secret_does_not_work(self):
        state = relay.sign_state("user-1", "kite", "s3cret")
        with self.assertRaises(relay.RelayError):
            relay.verify_state(state, "different")

    def test_an_old_state_expires(self):
        stale = relay.sign_state("user-1", "kite", "s3cret", now=1_000_000)
        relay.verify_state(stale, "s3cret", now=1_000_000 + relay.STATE_TTL - 1)
        with self.assertRaises(relay.RelayError):
            relay.verify_state(stale, "s3cret", now=1_000_000 + relay.STATE_TTL + 1)

    def test_garbage_is_refused_without_saying_why(self):
        # Distinguishing "forged" from "expired" hands an attacker an oracle.
        messages = set()
        for bad in ("", "nonsense", "a.b", "...."):
            with self.assertRaises(relay.RelayError) as raised:
                relay.verify_state(bad, "s3cret")
            messages.add(raised.exception.message)
        self.assertEqual(len(messages), 1)


class OrderValidationTest(unittest.TestCase):
    def test_accepts_ordinary_symbols(self):
        for symbol in ("RELIANCE", "TCS", "M&M", "BAJAJ-AUTO", "BRK.B"):
            self.assertEqual(relay.validate_order(symbol, 1, "buy")[0], symbol)

    def test_refuses_symbols_that_are_not_symbols(self):
        for bad in ("", "a" * 40, "DROP TABLE", "../etc", "RELIANCE;SELL", "<script>"):
            with self.assertRaises(relay.RelayError):
                relay.validate_order(bad, 1, "buy")

    def test_quantity_must_be_a_positive_whole_number(self):
        for bad in (0, -5, "many", None, relay.MAX_QTY + 1, 1.5):
            with self.assertRaises(relay.RelayError):
                relay.validate_order("TCS", bad, "buy")

    def test_side_is_buy_or_sell_only(self):
        with self.assertRaises(relay.RelayError):
            relay.validate_order("TCS", 1, "short")


class GuardTest(unittest.TestCase):
    """The refusals that stand between a request and real money."""

    def setUp(self):
        self.env = mock.patch.dict("os.environ", {
            "KITE_API_KEY": KEY, "KITE_API_SECRET": SECRET,
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def _place(self, **kwargs):
        args = dict(user_id="u", provider_name="kite", symbol="TCS",
                    qty=1, side="buy", price="100")
        args.update(kwargs)
        return relay.place_order(**args)

    def test_orders_are_off_unless_explicitly_armed(self):
        with mock.patch.dict("os.environ", {"BROKER_ORDERS_LIVE": ""}, clear=False):
            with self.assertRaises(relay.RelayError) as raised:
                self._place()
        self.assertEqual(raised.exception.status, 403)
        self.assertIn("BROKER_ORDERS_LIVE", raised.exception.message)

    def test_an_unconfigured_broker_refuses_before_anything_else(self):
        with mock.patch.dict("os.environ", {"KITE_API_KEY": ""}, clear=False):
            with self.assertRaises(relay.RelayError) as raised:
                self._place()
        self.assertEqual(raised.exception.status, 503)

    def test_a_buy_without_a_cap_is_refused(self):
        with mock.patch.dict("os.environ",
                             {"BROKER_ORDERS_LIVE": "true", "DAILY_CAP_INR": "0"},
                             clear=False), \
             mock.patch.object(relay, "read_link",
                               return_value=relay.Link("kite", "tok", "A1", None)):
            with self.assertRaises(relay.RelayError) as raised:
                self._place()
        self.assertIn("DAILY_CAP_INR", raised.exception.message)

    def test_the_cap_counts_what_was_already_placed(self):
        with mock.patch.dict("os.environ",
                             {"BROKER_ORDERS_LIVE": "true", "DAILY_CAP_INR": "10000"},
                             clear=False), \
             mock.patch.object(relay, "read_link",
                               return_value=relay.Link("kite", "tok", "A1", None)), \
             mock.patch.object(relay, "spent_today", return_value=Decimal("9500")):
            with self.assertRaises(relay.RelayError) as raised:
                self._place(qty=10, price="100")   # 1,000 more against 500 left
        self.assertEqual(raised.exception.status, 403)
        self.assertIn("daily cap", raised.exception.message)

    def test_an_expired_link_is_refused_rather_than_used(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with mock.patch.dict("os.environ",
                             {"BROKER_ORDERS_LIVE": "true", "DAILY_CAP_INR": "10000"},
                             clear=False), \
             mock.patch.object(relay, "read_link",
                               return_value=relay.Link("kite", "tok", "A1", yesterday)):
            with self.assertRaises(relay.RelayError) as raised:
                self._place()
        self.assertIn("expired", raised.exception.message)

    def test_an_unlinked_broker_is_refused(self):
        with mock.patch.dict("os.environ",
                             {"BROKER_ORDERS_LIVE": "true", "DAILY_CAP_INR": "10000"},
                             clear=False), \
             mock.patch.object(relay, "read_link", return_value=None):
            with self.assertRaises(relay.RelayError) as raised:
                self._place()
        self.assertIn("connect", raised.exception.message.lower())

    def test_a_price_is_required_because_the_cap_needs_one(self):
        with mock.patch.dict("os.environ",
                             {"BROKER_ORDERS_LIVE": "true", "DAILY_CAP_INR": "10000"},
                             clear=False), \
             mock.patch.object(relay, "read_link",
                               return_value=relay.Link("kite", "tok", "A1", None)):
            for bad in (None, "0", "-5"):
                with self.assertRaises(relay.RelayError):
                    self._place(price=bad)


class LinkTest(unittest.TestCase):
    def test_a_link_with_no_expiry_is_not_stale(self):
        self.assertFalse(relay.Link("kite", "t", "", None).stale())

    def test_a_past_expiry_is_stale(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.assertTrue(relay.Link("kite", "t", "", past).stale())

    def test_a_future_expiry_is_not(self):
        ahead = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self.assertFalse(relay.Link("kite", "t", "", ahead).stale())

    def test_an_unreadable_expiry_does_not_lock_the_reader_out(self):
        self.assertFalse(relay.Link("kite", "t", "", "not a date").stale())

    def test_expiry_is_the_next_six_am_ist(self):
        moment = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)
        expiry = datetime.fromisoformat(relay.next_expiry(now=moment))
        self.assertGreater(expiry, moment)
        self.assertEqual((expiry.hour, expiry.minute), (0, 30))


class ConfigurationTest(unittest.TestCase):
    def test_a_broker_without_credentials_is_not_offered(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(available(), [])

    def test_credentials_make_a_broker_available(self):
        with mock.patch.dict("os.environ",
                             {"KITE_API_KEY": KEY, "KITE_API_SECRET": SECRET},
                             clear=True):
            self.assertEqual([p.name for p in available()], ["kite"])

    def test_a_half_configured_broker_is_not_offered(self):
        # A key with no secret cannot complete the exchange, so offering the
        # button only produces a failure at the end of a login.
        with mock.patch.dict("os.environ", {"KITE_API_KEY": KEY}, clear=True):
            self.assertEqual(available(), [])

    def test_angel_one_needs_only_a_key(self):
        with mock.patch.dict("os.environ", {"ANGELONE_API_KEY": KEY}, clear=True):
            self.assertEqual([p.name for p in available()], ["angelone"])


class HoldingTest(unittest.TestCase):
    def test_value_and_pnl(self):
        h = Holding("TCS", Decimal("10"), Decimal("100"), Decimal("125"), "INR")
        self.assertEqual(h.value, Decimal("1250"))
        self.assertEqual(h.pnl, Decimal("250"))

    def test_a_loss_is_negative(self):
        h = Holding("TCS", Decimal("10"), Decimal("100"), Decimal("90"), "INR")
        self.assertEqual(h.pnl, Decimal("-100"))


if __name__ == "__main__":
    unittest.main()
