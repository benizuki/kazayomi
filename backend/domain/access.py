"""誰が何を見られ、何をできるか。

判定はロール名ではなく機能キー（can_xxx）で行う。ロールは機能キーの既定値のセットに過ぎない。
ロール名で分岐すると、「この人にだけ例外的に許可したい」が来たときにロールが増えて破綻するため。

見られる範囲は所属グループで決める。admin（can_manage_users を持つ人）は全グループを見られる。

権限は 2 段ある。
- 全体のロール（users.role）: 所属しているどのグループでも効く。admin・device_admin の管理の権限は全グループに効く
- グループでの役割（user_groups.role）: そのグループの中でだけ効く。owner（グループ管理者）は
  そのグループのメンバー・ルーム・デバイスを管理できる
あるグループで何ができるかは、この 2 つのうち強いほう（can_in）。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, Mapping, TypedDict

Role = Literal["admin", "device_admin", "power", "user"]
ROLES: tuple[Role, ...] = ("admin", "device_admin", "power", "user")


class Permissions(TypedDict):
    can_view: bool            # 映像・ライブラリ・アルバムを見る、撮像、通話
    can_edit: bool            # タグ・アルバムの編集、画像の削除・取り込み
    can_manage_devices: bool  # サーバ・ルーム・デバイスの編集、端末登録
    can_manage_users: bool    # ユーザー・グループの編集、監査ログ
    can_manage_members: bool  # グループのメンバーの招待・役割の変更・外す


def _perms(view: bool, edit: bool, devices: bool, users: bool, members: bool) -> Permissions:
    return {"can_view": view, "can_edit": edit, "can_manage_devices": devices,
            "can_manage_users": users, "can_manage_members": members}


def permissions_for_role(role: str) -> Permissions:
    """全体のロールの権限。"""
    if role == "admin":
        return _perms(True, True, True, True, True)
    if role == "device_admin":
        return _perms(True, True, True, False, False)
    if role == "power":
        return _perms(True, True, False, False, False)
    return _perms(True, False, False, False, False)


GroupRole = Literal["owner", "editor", "viewer"]
GROUP_ROLES: tuple[GroupRole, ...] = ("owner", "editor", "viewer")
GROUP_ROLE_LABELS: dict[str, str] = {"owner": "グループ管理者", "editor": "編集者", "viewer": "閲覧者"}


def permissions_for_group_role(role: str | None) -> Permissions:
    """グループでの役割の権限。そのグループの中でだけ効く（ユーザー管理は付かない）。"""
    if role == "owner":
        return _perms(True, True, True, False, True)
    if role == "editor":
        return _perms(True, True, False, False, False)
    if role == "viewer":
        return _perms(True, False, False, False, False)
    return _perms(False, False, False, False, False)


# 全体のロールで持っていれば、所属していないグループにも効く管理の権限
_GLOBAL_KEYS = frozenset({"can_manage_devices", "can_manage_users", "can_manage_members"})


PERMISSION_LABELS: dict[str, str] = {
    "can_view": "閲覧",
    "can_edit": "編集",
    "can_manage_devices": "デバイス管理",
    "can_manage_users": "ユーザー管理",
    "can_manage_members": "メンバー管理",
}


class ForbiddenError(PermissionError):
    """権限がない、または所属していないグループのものを触ろうとした。api 層で 403 にする。"""


@dataclass(frozen=True)
class Principal:
    """リクエストを送ってきたログイン中のユーザー。"""

    email: str
    name: str
    role: str
    permissions: Permissions
    # None は全グループ（admin）。空の集合は「どこにも所属していない」
    group_ids: frozenset[str] | None = field(default=None)
    # 所属グループでの役割（group_id → owner / editor / viewer）
    group_roles: Mapping[str, str] = field(default_factory=dict)
    # ゲスト（ユーザーのマスターにいない人）の識別子。"google:<sub>"。マスターにいる人は空
    subject: str = ""

    @property
    def is_guest(self) -> bool:
        return bool(self.subject)

    def has_global(self, key: str) -> bool:
        """全体のロールで持っているか（サーバの編集など、グループに属さないものに使う）。"""
        return bool(self.permissions.get(key))

    def can(self, key: str) -> bool:
        """どれかのグループで持っているか。画面のボタンを出すかや、API の入口の判定に使う。"""
        return self.has_global(key) or any(permissions_for_group_role(r).get(key) for r in self.group_roles.values())

    def can_in(self, group_id: str | None, key: str) -> bool:
        """そのグループで持っているか。全体のロールとグループでの役割の、強いほう。"""
        if group_id is None:
            return key in _GLOBAL_KEYS and self.has_global(key)
        if key in _GLOBAL_KEYS and self.has_global(key):
            return True
        if not self.can_see_group(group_id):
            return False
        return self.has_global(key) or bool(permissions_for_group_role(self.group_roles.get(group_id)).get(key))

    def require(self, key: str) -> None:
        if not self.can(key):
            label = PERMISSION_LABELS.get(key, key)
            raise ForbiddenError(f"この操作には{label}の権限が必要です。管理者に権限の付与を依頼してください。")

    def require_in(self, group_id: str | None, key: str) -> None:
        if not self.can_in(group_id, key):
            label = PERMISSION_LABELS.get(key, key)
            raise ForbiddenError(f"このグループでは{label}の権限がありません。グループの管理者に確認してください。")

    def require_global(self, key: str) -> None:
        if not self.has_global(key):
            label = PERMISSION_LABELS.get(key, key)
            raise ForbiddenError(f"この操作にはアプリ全体の{label}の権限が必要です。管理者に依頼してください。")

    def groups_with(self, key: str) -> frozenset[str] | None:
        """key を持っているグループ。None は全グループ。"""
        if key in _GLOBAL_KEYS and self.has_global(key):
            return None
        if self.group_ids is None:
            return None if self.has_global(key) else frozenset(g for g, r in self.group_roles.items()
                                                              if permissions_for_group_role(r).get(key))
        return frozenset(g for g in self.group_ids if self.can_in(g, key))

    def scoped(self, key: str) -> "Principal":
        """key を持っているグループだけが見える Principal にする。

        domain 層は「見えるグループ」で絞り込むので、これを渡すと「編集できるものだけ」を扱わせられる。
        """
        return replace(self, group_ids=self.groups_with(key))

    def effective_permissions(self) -> Permissions:
        """どれかのグループで持っている権限。画面の出し分けに使う。"""
        return {key: self.can(key) for key in PERMISSION_LABELS}  # type: ignore[return-value]

    @property
    def all_groups(self) -> bool:
        return self.group_ids is None

    def can_see_group(self, group_id: str | None) -> bool:
        return self.group_ids is None or (group_id is not None and group_id in self.group_ids)

    def require_group(self, group_id: str | None) -> None:
        if not self.can_see_group(group_id):
            # 存在そのものを伏せたいので「見つからない」と同じ言い方にする
            raise ForbiddenError("このグループのデータを扱う権限がありません。所属グループを管理者に確認してください。")

    def visible_group_ids(self) -> list[str] | None:
        """SQL の絞り込みに使う。None は絞り込まない。"""
        return None if self.group_ids is None else sorted(self.group_ids)
