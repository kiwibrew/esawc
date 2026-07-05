import asyncio
import sys
import secrets
from passlib.context import CryptContext
from sqlalchemy import select
from app.database import AsyncSessionLocal, init_db
from app.models.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def create_user(email, password):
    await init_db()
    async with AsyncSessionLocal() as session:
        # Check if user already exists
        result = await session.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            print(f"Error: User {email} already exists.")
            return

        hashed_password = pwd_context.hash(password)
        # Admins don't have bearer tokens per user clarification
        # But wait, user clarification said "Admin is not intended to have a bearer token"
        # but also "When any user is created through this process a bearer token should also be created and recorded."
        # I'll stick to: if is_admin=True, token is None (or empty).
        # Actually the prompt says "Python manage_users.py create admin@esawc.locnet.io passwordhere"
        # and "Insert the DB row setting the is_admin and is_active booleans to True"
        
        new_user = User(
            email=email,
            password_hash=hashed_password,
            is_admin=True,
            is_active=True,
            bearer_token=None # Admin doesn't have one
        )
        session.add(new_user)
        await session.commit()
        print(f"User {email} created successfully as admin.")

async def remove_user(email):
    await init_db()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            print(f"Error: User {email} not found.")
            return

        await session.delete(user)
        await session.commit()
        print(f"User {email} removed successfully.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python manage_users.py [create|remove] ...")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "create":
        if len(sys.argv) != 4:
            print("Usage: python manage_users.py create <email> <password>")
            sys.exit(1)
        email = sys.argv[2]
        password = sys.argv[3]
        asyncio.run(create_user(email, password))
    elif command == "remove":
        if len(sys.argv) != 3:
            print("Usage: python manage_users.py remove <email>")
            sys.exit(1)
        email = sys.argv[2]
        asyncio.run(remove_user(email))
    else:
        print(f"Unknown command: {command}")
        print("Usage: python manage_users.py [create|remove] ...")
        sys.exit(1)
