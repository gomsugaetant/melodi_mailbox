from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from core.db import Repository
from core.orm import select
from modules.melodi_mailbox.models.models import MailFolderModel, MailSyncStateModel


class MailFolderRepository(Repository):
    """Accès aux données pour les dossiers IMAP et leurs états de synchronisation."""

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
