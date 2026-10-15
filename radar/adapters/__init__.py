"""Source adapters package: the `Adapter` contract and the live registry.

`ADAPTERS` maps source id -> adapter instance. Task 3 registered devpost;
Task 4 added devfolio (browser kind); Task 8 adds mlh, dorahacks and
superteam (browser kind); Task 9 adds lablab, ethglobal and taikai
(browser kind); Task 10 adds hackathoncom, wemakedevs and hackclub
(browser kind; later tasks append more entries, with matching
`radar/sources.yaml` rows).
"""

from radar.adapters.base import Adapter
from radar.adapters.devfolio import DevfolioAdapter
from radar.adapters.devpost import DevpostAdapter
from radar.adapters.dorahacks import DorahacksAdapter
from radar.adapters.ethglobal import EthglobalAdapter
from radar.adapters.hackathoncom import HackathoncomAdapter
from radar.adapters.hackclub import HackclubAdapter
from radar.adapters.lablab import LablabAdapter
from radar.adapters.mlh import MlhAdapter
from radar.adapters.superteam import SuperteamAdapter
from radar.adapters.taikai import TaikaiAdapter
from radar.adapters.wemakedevs import WemakedevsAdapter

ADAPTERS: dict[str, Adapter] = {
    DevfolioAdapter.id: DevfolioAdapter(),
    DevpostAdapter.id: DevpostAdapter(),
    DorahacksAdapter.id: DorahacksAdapter(),
    EthglobalAdapter.id: EthglobalAdapter(),
    HackathoncomAdapter.id: HackathoncomAdapter(),
    HackclubAdapter.id: HackclubAdapter(),
    LablabAdapter.id: LablabAdapter(),
    MlhAdapter.id: MlhAdapter(),
    SuperteamAdapter.id: SuperteamAdapter(),
    TaikaiAdapter.id: TaikaiAdapter(),
    WemakedevsAdapter.id: WemakedevsAdapter(),
}
