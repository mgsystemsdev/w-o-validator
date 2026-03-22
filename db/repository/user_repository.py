from __future__ import annotations

from psycopg2.extras import RealDictCursor

from db.connection import get_connection, transaction


def get_user_by_id(user_id: str) -> dict | None:
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        return cur.fetchone()


def count_users() -> int:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        return cur.fetchone()[0]


def create_user(user_id: str, email: str, username: str, is_admin: bool) -> dict:
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO users (user_id, email, username, is_admin)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (user_id, email, username, is_admin),
        )
        return cur.fetchone()


def set_user_active(user_id: str, is_active: bool) -> None:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET is_active = %s WHERE user_id = %s",
            (is_active, user_id),
        )


def list_users() -> list[dict]:
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM users ORDER BY username")
        return cur.fetchall()


def get_user_properties(user_id: str) -> list[int]:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT property_id FROM user_properties WHERE user_id = %s ORDER BY property_id",
            (user_id,),
        )
        return [row[0] for row in cur.fetchall()]


def set_user_properties(user_id: str, property_ids: list[int]) -> None:
    with transaction():
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_properties WHERE user_id = %s", (user_id,))
            if property_ids:
                cur.executemany(
                    "INSERT INTO user_properties (user_id, property_id) VALUES (%s, %s)",
                    [(user_id, pid) for pid in property_ids],
                )


def list_all_users_with_properties() -> list[dict]:
    """Return all users with their assigned property_ids aggregated into a list."""
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                u.user_id,
                u.email,
                u.username,
                u.is_admin,
                u.is_active,
                u.created_at,
                COALESCE(
                    ARRAY_AGG(up.property_id ORDER BY up.property_id)
                    FILTER (WHERE up.property_id IS NOT NULL),
                    ARRAY[]::BIGINT[]
                ) AS property_ids
            FROM users u
            LEFT JOIN user_properties up ON up.user_id = u.user_id
            GROUP BY u.user_id
            ORDER BY u.username
            """
        )
        return cur.fetchall()
