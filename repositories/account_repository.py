from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import delete as sqla_delete
from sqlalchemy import or_, update as sqla_update

from core.db import Repository
from core.orm import select
from modules.melodi_mailbox.models.models import (
    MailAccountAccessModel,
    MailAccountModel,
    MailIdentityModel,
)


class MailAccountRepository(Repository):
    """Accès aux données pour les comptes email, identités et partages ACL."""

    async def list_accessible_accounts(
        self,
        organization_id: str,
        user_id: str,
        include_inactive: bool = False,
        is_sudo: bool = False,
        session=None,
    ) -> list[MailAccountModel]:
        async def _run(s):
            stmt = select(MailAccountModel).where(
                MailAccountModel.organization_id == organization_id
            )
            if not include_inactive:
                stmt = stmt.where(MailAccountModel.is_active.is_(True))

            if not is_sudo:
                access_subq = (
                    select(MailAccountAccessModel.account_id)
                    .where(
                        MailAccountAccessModel.user_id == user_id,
                        MailAccountAccessModel.can_read.is_(True),
                    )
                    .scalar_subquery()
                )
                stmt = stmt.where(
                    or_(
                        MailAccountModel.owner_user_id == user_id,
                        MailAccountModel.account_id.in_(access_subq),
                    )
                )

            stmt = stmt.order_by(
                MailAccountModel.is_default.desc(),
                MailAccountModel.created_at.asc(),
            )
            res = await s.execute(stmt)
            return list(res.scalars().all())

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def get_by_id(
        self,
        account_id: str,
        organization_id: Optional[str] = None,
        session=None,
    ) -> Optional[MailAccountModel]:
        async def _run(s):
            stmt = select(MailAccountModel).where(MailAccountModel.account_id == account_id)
            if organization_id is not None:
                stmt = stmt.where(MailAccountModel.organization_id == organization_id)
            res = await s.execute(stmt)
            return res.scalar_one_or_none()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def get_by_org_owner_email(
        self,
        organization_id: str,
        owner_user_id: str,
        email_address: str,
        session=None,
    ) -> Optional[MailAccountModel]:
        async def _run(s):
            stmt = select(MailAccountModel).where(
                MailAccountModel.organization_id == organization_id,
                MailAccountModel.owner_user_id == owner_user_id,
                MailAccountModel.email_address == email_address.lower(),
            )
            res = await s.execute(stmt)
            return res.scalar_one_or_none()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def get_access_for_user(
        self,
        account_id: str,
        user_id: str,
        session=None,
    ) -> Optional[MailAccountAccessModel]:
        async def _run(s):
            stmt = select(MailAccountAccessModel).where(
                MailAccountAccessModel.account_id == account_id,
                MailAccountAccessModel.user_id == user_id,
            )
            res = await s.execute(stmt)
            return res.scalar_one_or_none()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def clear_default_for_owner(
        self,
        organization_id: str,
        owner_user_id: str,
        exclude_account_id: Optional[str] = None,
        session=None,
    ) -> None:
        async def _run(s):
            stmt = (
                sqla_update(MailAccountModel)
                .where(
                    MailAccountModel.organization_id == organization_id,
                    MailAccountModel.owner_user_id == owner_user_id,
                )
                .values(is_default=False, updated_at=datetime.utcnow())
            )
            if exclude_account_id:
                stmt = stmt.where(MailAccountModel.account_id != exclude_account_id)
            await s.execute(stmt)

        if session is not None:
            await _run(session)
            return
        async with self.get_session() as s:
            await _run(s)
            await s.commit()

    async def create(self, account: MailAccountModel, session=None) -> MailAccountModel:
        if session is not None:
            session.add(account)
            await session.flush()
            return account
        async with self.get_session() as s:
            s.add(account)
            await s.commit()
            await s.refresh(account)
            return account

    async def update_fields(
        self,
        account_id: str,
        values: dict,
        session=None,
    ) -> Optional[MailAccountModel]:
        values = {**values, "updated_at": datetime.utcnow()}

        async def _run(s):
            stmt = (
                sqla_update(MailAccountModel)
                .where(MailAccountModel.account_id == account_id)
                .values(**values)
            )
            await s.execute(stmt)
            return await self.get_by_id(account_id, session=s)

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            updated = await _run(s)
            await s.commit()
            return updated

    async def delete_by_id(self, account_id: str, session=None) -> bool:
        async def _run(s):
            stmt = sqla_delete(MailAccountModel).where(MailAccountModel.account_id == account_id)
            res = await s.execute(stmt)
            return (res.rowcount or 0) > 0

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            deleted = await _run(s)
            await s.commit()
            return deleted

    # ── Identités ─────────────────────────────────────────────────────────────

    async def create_identity(self, identity: MailIdentityModel, session=None) -> MailIdentityModel:
        if session is not None:
            session.add(identity)
            await session.flush()
            return identity
        async with self.get_session() as s:
            s.add(identity)
            await s.commit()
            await s.refresh(identity)
            return identity

    async def list_identities(self, account_id: str, session=None) -> list[MailIdentityModel]:
        async def _run(s):
            stmt = (
                select(MailIdentityModel)
                .where(MailIdentityModel.account_id == account_id)
                .order_by(MailIdentityModel.is_default.desc(), MailIdentityModel.created_at.asc())
            )
            res = await s.execute(stmt)
            return list(res.scalars().all())

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)
