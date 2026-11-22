"""Ballot service — turns the boxes ticked on the entry form into vote records.

Counting rules (the same for every post):

* A post allows `max_selections` votes: 1 for every post, 3 for Executive
  Member (নির্বাহী সদস্য).
* If MORE boxes than that are marked for a post, every mark of that post is a
  null vote: stored (so the ballot can be shown exactly as entered) but flagged
  invalid and never counted.  So two marks for President -> no vote for
  President; four marks for Executive Member -> no vote for Executive Member.
* A mark that is not very clear is still a mark: if the other box(es) of the
  post are purely empty, the commissioner ticks it and it counts.  Only a voter
  who touched more boxes of a post than it allows makes that post invalid.
* The other posts of the same ballot are not affected, and a ballot is never
  rejected as a whole.  A post with no mark simply has no vote.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ballot, Candidate, Position, Vote
from app.services.events import notifier

logger = logging.getLogger(__name__)


def null_reason(marked: int, allowed: int) -> str:
    return f"Null vote: {marked} marked, only {allowed} allowed for this post"


class BallotService:
    @staticmethod
    async def layout(db: AsyncSession, election_id: int) -> tuple[list[Position], dict[int, Candidate]]:
        """Positions in ballot order and every candidate by id."""
        positions = (await db.execute(
            select(Position).where(Position.election_id == election_id).order_by(Position.position_order)
        )).scalars().all()
        candidates = {c.id: c for p in positions for c in p.candidates}
        return list(positions), candidates

    @staticmethod
    def preview(positions: list[Position], candidates: dict[int, Candidate], candidate_ids: list[int]) -> tuple[int, int]:
        """(votes that count, null marks) the rules give for these ticked boxes, without storing anything."""
        per_post: dict[int, int] = {}
        for candidate_id in set(candidate_ids):
            candidate = candidates.get(candidate_id)
            if candidate is not None:
                per_post[candidate.position_id] = per_post.get(candidate.position_id, 0) + 1
        allowed = {p.id: p.max_selections for p in positions}
        counted = sum(n for post, n in per_post.items() if n <= allowed.get(post, 1))
        return counted, sum(per_post.values()) - counted

    async def store_votes(self, db: AsyncSession, ballot: Ballot, candidate_ids: list[int]) -> dict:
        """Insert the votes of `ballot` for the marked boxes and apply the rules.

        Raises ValueError for a candidate that is not on this election's ballot.
        Returns a summary: counted votes, null marks and the posts that were voided.
        """
        positions, candidates = await self.layout(db, ballot.election_id)
        marked = list(dict.fromkeys(candidate_ids))  # a box is ticked once
        unknown = [cid for cid in marked if cid not in candidates]
        if unknown:
            raise ValueError(f"Candidate {unknown[0]} is not on this ballot")

        by_position: dict[int, list[int]] = {}
        for candidate_id in marked:
            by_position.setdefault(candidates[candidate_id].position_id, []).append(candidate_id)

        counted, null_marks = 0, 0
        warnings: list[str] = []
        null_posts: list[dict] = []
        for position in positions:
            chosen = by_position.get(position.id, [])
            if not chosen:
                continue
            over = len(chosen) > position.max_selections
            reason = null_reason(len(chosen), position.max_selections) if over else None
            if over:
                null_marks += len(chosen)
                null_posts.append({
                    "position_id": position.id, "name_en": position.name_en, "name_bn": position.name_bn,
                    "marked": len(chosen), "allowed": position.max_selections,
                })
                warnings.append(f"{position.name_en}: {len(chosen)} marked, only {position.max_selections} allowed (null vote)")
            for candidate_id in chosen:
                db.add(Vote(
                    ballot_id=ballot.id, candidate_id=candidate_id, position_id=position.id,
                    is_valid=not over, invalid_reason=reason, confidence_score=1.0,
                ))
                if not over:
                    counted += 1
                    await db.execute(
                        update(Candidate).where(Candidate.id == candidate_id)
                        .values(vote_count=Candidate.vote_count + 1)
                    )

        ballot.total_votes_extracted = counted
        ballot.boxes_detected = len(marked)
        ballot.boxes_expected = len(candidates)
        ballot.ocr_warnings = json.dumps(warnings) if warnings else None
        ballot.is_valid = True
        return {"counted": counted, "null_marks": null_marks, "null_posts": null_posts, "marked": len(marked)}

    async def remove_votes(self, db: AsyncSession, ballot: Ballot) -> None:
        """Delete a ballot's votes and roll back the candidate counters."""
        result = await db.execute(select(Vote).where(Vote.ballot_id == ballot.id))
        for vote in result.scalars().all():
            if vote.is_valid:
                await db.execute(
                    update(Candidate).where(Candidate.id == vote.candidate_id)
                    .values(vote_count=Candidate.vote_count - 1)
                )
            await db.delete(vote)
        await db.flush()
        await db.refresh(ballot, attribute_names=["votes"])  # drop the stale collection

    async def recount_votes(self, db: AsyncSession, election_id: int) -> None:
        """Rebuild the denormalised counters from the vote records."""
        await db.execute(update(Candidate).where(Candidate.election_id == election_id).values(vote_count=0))
        result = await db.execute(
            select(Vote.candidate_id, func.count(Vote.id))
            .join(Ballot, Vote.ballot_id == Ballot.id)
            .where(Ballot.election_id == election_id, Vote.is_valid.is_(True), Ballot.is_valid.is_(True))
            .group_by(Vote.candidate_id)
        )
        for candidate_id, count in result.all():
            await db.execute(update(Candidate).where(Candidate.id == candidate_id).values(vote_count=count))
        await db.commit()
        notifier.notify()
        logger.info("Recount completed for election %s", election_id)


ballot_service = BallotService()
