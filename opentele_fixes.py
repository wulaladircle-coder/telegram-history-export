"""Runtime fixes for opentele 1.15.1 (last released 2022) so it can read
tdata written by current Telegram Desktop versions. Applied by monkey-patching,
no need to edit site-packages.

Fix 1: newer Telegram Desktop writes map data with unknown key types
(e.g. 23); opentele aborts loading the account. The map only stores drafts
and sticker metadata, auth keys live in a separate file, so we skip it.

Fix 2: TDesktop.api setter <-> Account.api setter ping-pong causes infinite
recursion when loading more than one account; set the private attr directly.
"""

from PyQt5.QtCore import QByteArray

from opentele.exception import OpenTeleException
from opentele.td.account import StorageAccount, Account
from opentele.td.tdesktop import TDesktop


def _read_map_with(self, localKey, legacyPasscode=None):
    try:
        self._StorageAccount__mapData.read(localKey, legacyPasscode or QByteArray())
    except OpenTeleException as e:
        print(f"warning: map data skipped ({e})")
    self.readMtpData()


def _api_setter(self, value):
    self._TDesktop__api = value
    for account in self.accounts:
        account._Account__api = value


def apply():
    StorageAccount.readMapWith = _read_map_with
    TDesktop.api = property(TDesktop.api.fget, _api_setter)
