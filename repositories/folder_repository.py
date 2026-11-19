from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import update as sqla_update

from core.db import Repository
from core.orm import func, select
from modules.melodi_mailbox.models.models import MailFolderModel, MailMessageModel, MailSyncStateModel


class MailFolderRepository(Repository):
    """Accès aux données pour les dossiers IMAP et leurs états de synchronisation."""

    async def get_by_id(self, folder_id: str, session=None) -> Optional[MailFolderModel]:
        async def _run(s):
            stmt = select(MailFolderModel).where(MailFolderModel.folder_id == folder_id)
            res = await s.execute(stmt)
            return res.scalar_one_or_none()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def get_by_type(
        self, account_id: str, folder_type: str, session=None
    ) -> Optional[MailFolderModel]:
        async def _run(s):
            stmt = (
                select(MailFolderModel)
                .where(
                    MailFolderModel.account_id == account_id,
                    MailFolderModel.folder_type == folder_type,
                )
                .order_by(MailFolderModel.sort_order.asc())
            )
            res = await s.execute(stmt)
            return res.scalars().first()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def list_by_account(self, account_id: str, session=None) -> list[MailFolderModel]:
        async def _run(s):
            stmt = (
                select(MailFolderModel)
                .where(MailFolderModel.account_id == account_id)
                .order_by(MailFolderModel.sort_order.asc(), MailFolderModel.name.asc())
            )
            res = await s.execute(stmt)
            return list(res.scalars().all())

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def get_sync_state(
        self, account_id: str, folder_id: str, session=None
    ) -> Optional[MailSyncStateModel]:
        async def _run(s):
            stmt = select(MailSyncStateModel).where(
                MailSyncStateModel.account_id == account_id,
                MailSyncStateModel.folder_id == folder_id,
            )
            res = await s.execute(stmt)
            return res.scalar_one_or_none()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def upsert_sync_state(
        self,
        account_id: str,
        folder_id: str,
        organization_id: str,
        values: dict,
        session=None,
    ) -> MailSyncStateModel:
        async def _run(s):
            state = await self.get_sync_state(account_id, folder_id, session=s)
            if state is None:
                state = MailSyncStateModel(
                    sync_state_id=str(uuid.uuid4()),
                    account_id=account_id,
                    folder_id=folder_id,
                    organization_id=organization_id,
                    **values,
                )
                s.add(state)
            else:
                for k, v in values.items():
                    setattr(state, k, v)
                state.updated_at = datetime.utcnow()
            await s.flush()
            return state

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            st = await _run(s)
            await s.commit()
            return st

    async def refresh_folder_counts(self, folder_id: str, session=None) -> None:
        async def _run(s):
            total_stmt = select(func.count(MailMessageModel.message_id)).where(
                MailMessageModel.folder_id == folder_id
            )
            unread_stmt = select(func.count(MailMessageModel.message_id)).where(
                MailMessageModel.folder_id == folder_id,
                MailMessageModel.is_read.is_(False),
            )
            total_cnt = (await s.execute(total_stmt)).scalar() or 0
            unread_cnt = (await s.execute(unread_stmt)).scalar() or 0
            await s.execute(
                sqla_update(MailFolderModel)
                .where(MailFolderModel.folder_id == folder_id)
                .values(
                    total_count=int(total_cnt),
                    unread_count=int(unread_cnt),
                    updated_at=datetime.utcnow(),
                )
            )

        if session is not None:
            await _run(session)
            return
        async with self.get_session() as s:
            await _run(s)
            await s.commit()

    async def upsert_folders(
        self,
        account_id: str,
        organization_id: str,
        folders_data: list[dict],
        session=None,
    ) -> list[MailFolderModel]:
        async def _run(s):
            existing = await self.list_by_account(account_id, session=s)
            by_remote = {f.remote_name: f for f in existing}
            result: list[MailFolderModel] = []

            for item in folders_data:
                remote_name = item["remote_name"]
                folder = by_remote.get(remote_name)
                if folder is None:
                    folder = MailFolderModel(
                        folder_id=str(uuid.uuid4()),
                        account_id=account_id,
                        organization_id=organization_id,
                        name=item["name"],
                        remote_name=remote_name,
                        delimiter=item.get("delimiter") or "/",
                        folder_type=item.get("folder_type") or "custom",
                        sort_order=int(item.get("sort_order", 100)),
                    )
                    s.add(folder)
                    await s.flush()

                    # Initialiser l'état de synchronisation du dossier
                    sync_state = MailSyncStateModel(
                        sync_state_id=str(uuid.uuid4()),
                        account_id=account_id,
                        folder_id=folder.folder_id,
                        organization_id=organization_id,
                        last_uid=0,
                        status="idle",
                    )
                    s.add(sync_state)
                else:
                    folder.name = item["name"]
                    folder.folder_type = item.get("folder_type") or folder.folder_type
                    folder.delimiter = item.get("delimiter") or folder.delimiter
                    folder.sort_order = int(item.get("sort_order", folder.sort_order))
                    folder.updated_at = datetime.utcnow()
                result.append(folder)

            await s.flush()
            return result

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            rows = await _run(s)
            await s.commit()
            return rows
