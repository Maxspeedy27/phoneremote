import os
import sys
import unittest

from phoneremote.crypto import b64d, new_key, seal, unseal
from phoneremote.pairing import Pairing, PairingError

from helpers import Approver, temp_store


class Phone:
    """Plays the phone's side of the protocol, like web/app.js does."""

    def __init__(self, pairing_fragment):
        self.pairing_key = b64d(pairing_fragment.split("=", 1)[1])
        self.device_id = self.device_key = self.session = None
        self.seq = 0

    def pair_message(self, name="Test phone"):
        return seal(self.pairing_key, {"t": "pair", "name": name})

    def accept_pairing(self, reply):
        data = unseal(self.pairing_key, reply)
        self.device_id, self.device_key = data["id"], b64d(data["key"])

    def hello_message(self):
        msg = seal(self.device_key, {"t": "hello"})
        msg["d"] = self.device_id
        return msg

    def accept_session(self, reply):
        self.session = unseal(self.device_key, reply)["s"]
        self.seq = 0

    def command(self, ops, seq=None):
        self.seq = self.seq + 1 if seq is None else seq
        msg = seal(self.device_key, {"t": "cmd", "s": self.session, "q": self.seq, "ops": ops})
        msg["d"] = self.device_id
        return msg


class PairingTest(unittest.TestCase):
    def setUp(self):
        self.store = temp_store(self)
        self.approver = Approver(True)
        self.key_changes = []
        self.pairing = Pairing(self.store, self.approver, host="laptop",
                               on_key_changed=self.key_changes.append)

    def paired_phone(self):
        phone = Phone(self.pairing.pairing_fragment())
        phone.accept_pairing(self.pairing.pair(phone.pair_message()))
        _, reply = self.pairing.hello(phone.hello_message())
        phone.accept_session(reply)
        return phone

    def assertRejected(self, code, func, *args):
        with self.assertRaises(PairingError) as ctx:
            func(*args)
        self.assertEqual(ctx.exception.code, code)

    def test_full_flow(self):
        phone = self.paired_phone()
        ops = [{"a": "key", "k": "next"}]
        self.assertEqual(self.pairing.open_command(phone.command(ops)), ops)
        self.assertEqual(self.approver.prompts[0][0], "Test phone")
        self.assertEqual(self.key_changes, ["paired"])

    def test_qr_code_is_single_use(self):
        phone = Phone(self.pairing.pairing_fragment())
        msg = phone.pair_message()
        self.pairing.pair(msg)
        self.assertRejected("pairing-expired", self.pairing.pair, msg)
        # A fresh request made with the photographed (old) QR key fails too.
        self.assertRejected("pairing-expired", self.pairing.pair, phone.pair_message())

    def test_refusal_rotates_key_and_pairs_nothing(self):
        self.approver.answer = False
        phone = Phone(self.pairing.pairing_fragment())
        self.assertRejected("denied", self.pairing.pair, phone.pair_message())
        self.assertIsNone(self.pairing.device)
        self.assertEqual(self.key_changes, ["refused"])
        self.assertRejected("pairing-expired", self.pairing.pair, phone.pair_message())

    def test_wrong_pairing_key_never_prompts(self):
        phone = Phone(self.pairing.pairing_fragment())
        phone.pairing_key = new_key()
        self.assertRejected("pairing-expired", self.pairing.pair, phone.pair_message())
        self.assertEqual(self.approver.prompts, [])

    def test_replayed_command_rejected(self):
        phone = self.paired_phone()
        msg = phone.command([{"a": "key", "k": "next"}])
        self.pairing.open_command(msg)
        self.assertRejected("session", self.pairing.open_command, msg)

    def test_out_of_order_sequence_rejected(self):
        phone = self.paired_phone()
        self.pairing.open_command(phone.command([], seq=5))
        self.assertRejected("session", self.pairing.open_command, phone.command([], seq=5))
        self.assertRejected("session", self.pairing.open_command, phone.command([], seq=4))
        self.pairing.open_command(phone.command([], seq=6))

    def test_old_session_rejected_after_new_hello(self):
        phone = self.paired_phone()
        old = phone.command([])
        _, reply = self.pairing.hello(phone.hello_message())
        phone.accept_session(reply)
        self.assertRejected("session", self.pairing.open_command, old)
        self.pairing.open_command(phone.command([]))

    def test_commands_with_wrong_device_key_rejected(self):
        phone = self.paired_phone()
        phone.device_key = new_key()
        self.assertRejected("unpaired", self.pairing.open_command, phone.command([]))
        self.assertRejected("unpaired", self.pairing.hello, phone.hello_message())

    def test_message_types_cannot_be_swapped(self):
        phone = self.paired_phone()
        hello = phone.hello_message()
        self.assertRejected("bad-request", self.pairing.open_command, hello)

    def test_pairing_new_phone_replaces_old(self):
        first = self.paired_phone()
        second = self.paired_phone()
        self.assertRejected("unpaired", self.pairing.open_command, first.command([]))
        self.pairing.open_command(second.command([]))

    def test_paired_phone_survives_restart(self):
        phone = self.paired_phone()
        restarted = Pairing(self.store, Approver(False))
        _, reply = restarted.hello(phone.hello_message())
        phone.accept_session(reply)
        restarted.open_command(phone.command([]))

    def test_forget(self):
        phone = self.paired_phone()
        self.pairing.forget()
        self.assertRejected("unpaired", self.pairing.hello, phone.hello_message())
        self.assertIsNone(self.store.load())

    @unittest.skipIf(sys.platform.startswith("win"), "POSIX permissions")
    def test_store_file_is_private(self):
        self.paired_phone()
        self.assertEqual(os.stat(self.store.path).st_mode & 0o777, 0o600)

    def test_corrupt_store_means_unpaired(self):
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text("{not json")
        self.assertIsNone(self.store.load())

    def test_phone_name_is_sanitized(self):
        phone = Phone(self.pairing.pairing_fragment())
        self.pairing.pair(phone.pair_message(name="\x1b[31mEvil\n" + "x" * 100))
        name = self.approver.prompts[0][0]
        self.assertTrue(name.isprintable())
        self.assertLessEqual(len(name), 40)


if __name__ == "__main__":
    unittest.main()
