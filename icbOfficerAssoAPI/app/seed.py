"""First-start data: the five user accounts and the 2026 election with its ballot.

Both are created only when missing, so a password changed later, or an
election edited in the admin panel, is never overwritten.  The ballot number
ranges of the Election Commissioners follow ENTRY_RANGES on every start.
"""

import logging

from sqlalchemy import func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Candidate, Election, Position
from app.models.admin_user import AdminUser, Role
from app.models.election import ElectionStatus
from app.utils.security import hash_password

logger = logging.getLogger(__name__)

# username, first password, full name, role
DEFAULT_USERS = [
    ("SA", "sadmin", "Super Admin", Role.SUPERADMIN),
    ("Admin", "admin", "Admin", Role.ADMIN),
    ("EC1", "EC1", "Election Commissioner 1", Role.EC),
    ("EC2", "EC2", "Election Commissioner 2", Role.EC),
    ("EC3", "EC3", "Election Commissioner 3", Role.EC),
]

ELECTION_TITLE_BN = "আইসিবি কর্মকর্তা সমিতির ২০তম কার্যনির্বাহী পরিষদ নির্বাচন-২০২৬"
ELECTION_TITLE_EN = "ICB Officers' Association 20th Executive Council Election 2026"
ELECTION_YEAR = 2026

# The 13 posts printed on the ballot, in ballot order: (English, Bengali, votes allowed)
DEFAULT_POSITIONS = [
    ("President", "সভাপতি", 1),
    ("Vice President", "সহ-সভাপতি", 1),
    ("General Secretary", "সাধারণ সম্পাদক", 1),
    ("Asst. General Secretary", "সহকারী সাধারণ সম্পাদক", 1),
    ("Treasurer", "কোষাধ্যক্ষ", 1),
    ("Organizing Secretary", "সাংগঠনিক সম্পাদক", 1),
    ("Office Secretary", "দপ্তর সম্পাদক", 1),
    ("Publication Secretary", "প্রকাশনা সম্পাদক", 1),
    ("Cultural Secretary", "সাংস্কৃতিক সম্পাদক", 1),
    ("Drama Secretary", "নাট্য সম্পাদক", 1),
    ("Sports Secretary", "ক্রীড়া সম্পাদক", 1),
    ("Hospitality Secretary", "আপ্যায়ন সম্পাদক", 1),
    ("Executive Member", "নির্বাহী সদস্য", 3),
]

# The ballot of the 2026 election (Blank_ballot_form 2_Final_Format.docx), row by
# row: post number, voter no, English name, name as printed.  Within a post the
# order is left box, right box, next row left, next row right ...
BALLOT_2026 = [
    (1, "13", "A. K. M. Nuruzzaman", "জনাব এ, কে, এম, নূরুজ্জামান"),
    (1, "12", "Md. Jahirul Islam Khan", "জনাব মোঃ জহিরুল ইসলাম খান"),
    (2, "30", "Md. Mofizul Islam", "জনাব মোঃ মফিজুল ইসলাম"),
    (2, "28", "Jahangir Hossain", "জনাব জাহাঙ্গীর হোসেন"),
    (3, "74", "Mainuddin Ahmed", "জনাব মাঈনুদ্দিন আহমেদ"),
    (3, "40", "Kafil Uddin Patwary", "জনাব কফিল উদ্দিন পাটোয়ারী"),
    (4, "90", "Mohammad Mostafijur Rahman", "জনাব মোহাম্মদ মোস্তাফিজুর রহমান"),
    (4, "68", "Md. Abu Taleb", "জনাব মোঃ আবু তালেব"),
    (5, "124", "A.K.M. Moshiur Rahman", "জনাব এ. কে. এম. মশিউর রহমান"),
    (5, "70", "S. M. Shaiqul Alam", "জনাব এস, এম, সাইকুল আলম"),
    (6, "99", "Md. Masud Rana Pk.", "জনাব মোঃ মাসুদ রানা প্রাং"),
    (6, "113", "Md. Humayun Kabir", "জনাব মোঃ হুমায়ুন কবীর"),
    (7, "126", "Md. Khairul Islam", "জনাব মোঃ খায়রুল ইসলাম"),
    (7, "144", "Md. Athekur Rahman", "জনাব মোঃ আতিকুর রহমান"),
    (8, "247", "Tamal Datta", "জনাব তমাল দত্ত"),
    (8, "134", "Tofayel Ahmmad", "জনাব তোফায়েল আহমেদ"),
    (9, "174", "Md. Shariful-Islam", "জনাব মোঃ শরিফুল ইসলাম"),
    (9, "283", "Mahabub Hasan", "জনাব মাহবুব হাসান"),
    (10, "354", "Prantick Bala", "জনাব প্রান্তিক বালা"),
    (10, "257", "Rajib Chandra Pal", "জনাব রাজিব চন্দ্র পাল"),
    (11, "323", "Md. Tariqul Islam", "জনাব মোঃ তরিকুল ইসলাম"),
    (11, "345", "Md. Abdul Ahad Rafi", "জনাব মোঃ আব্দুল আহাদ রাফি"),
    (12, "336", "Faisal Kabir", "জনাব ফয়ছাল কবীর"),
    (12, "186", "Khaled Morshed Miah", "জনাব খালেদ মোর্শেদ মিয়া"),
    (13, "20", "Md. Nasim Ahmed", "জনাব মোঃ নাসিম আহম্মেদ"),
    (13, "76", "Md. Mohiuddin", "জনাব মোঃ মহিউদ্দীন"),
    (13, "33", "Tapas Dhali", "জনাব তাপস ঢালী"),
    (13, "237", "Fokoruddin Howlader", "জনাব ফকরদ্দিন হাওলাদার"),
    (13, "35", "Muhammed Tauhid Ahmed", "জনাব মোহাম্মদ তৌহিদ আহমদ"),
    (13, "431", "Md. Golam Kibria", "জনাব মোঃ গোলাম কিবরিয়া"),
]


async def ensure_users() -> None:
    """Create the missing default accounts; keep the EC number ranges in step with ENTRY_RANGES."""
    ranges = settings.entry_ranges
    async with AsyncSessionLocal() as db:
        existing = {u.username.lower(): u for u in (await db.execute(select(AdminUser))).scalars().all()}
        for username, password, full_name, role in DEFAULT_USERS:
            user = existing.get(username.lower())
            if user is None:
                user = AdminUser(username=username, password_hash=hash_password(password), full_name=full_name, role=role)
                db.add(user)
                logger.info("User '%s' (%s) created", username, role)
        await db.flush()
        by_name = {name.lower(): span for name, span in ranges.items()}
        for user in (await db.execute(select(AdminUser))).scalars().all():
            span = by_name.get(user.username.lower()) if user.role == Role.EC else None
            wanted = span or (None, None)
            if (user.ballot_from, user.ballot_to) != wanted:
                user.ballot_from, user.ballot_to = wanted
                logger.info("Ballot range of %s: %s", user.username, f"{wanted[0]}-{wanted[1]}" if span else "none")
        await db.commit()


async def ensure_election() -> None:
    """On an empty database create the 2026 election, its 13 posts and 30 candidates, ready for entry."""
    async with AsyncSessionLocal() as db:
        if (await db.execute(select(func.count(Election.id)))).scalar():
            return
        election = Election(
            title=ELECTION_TITLE_EN, title_bn=ELECTION_TITLE_BN, year=ELECTION_YEAR,
            status=ElectionStatus.ACTIVE, total_voters=settings.TOTAL_VOTERS,
            dashboard_published=True,  # the dashboard shows the running summary from the first ballot (Admin can hide it)
        )
        db.add(election)
        await db.flush()
        await add_ballot_2026(db, election.id)
        await db.commit()
        logger.info("Election '%s' created with %d posts and %d candidates", election.title, len(DEFAULT_POSITIONS), len(BALLOT_2026))


async def add_ballot_2026(db, election_id: int) -> None:
    """The 13 posts and the 30 candidates of the 2026 ballot paper."""
    positions: dict[int, Position] = {}
    for order, (name_en, name_bn, seats) in enumerate(DEFAULT_POSITIONS, start=1):
        positions[order] = Position(
            election_id=election_id, position_order=order, name_en=name_en, name_bn=name_bn, max_selections=seats,
        )
        db.add(positions[order])
    await db.flush()
    next_order: dict[int, int] = {}
    for post_no, voter_no, name_en, name_bn in BALLOT_2026:
        order = next_order.get(post_no, 0)
        next_order[post_no] = order + 1
        db.add(Candidate(
            election_id=election_id, position_id=positions[post_no].id, voter_no=voter_no,
            name_en=name_en, name_bn=name_bn, display_order=order,
        ))
