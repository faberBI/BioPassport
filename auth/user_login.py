import json
import os
import bcrypt

USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_users(users: dict):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def check_login(username: str, password: str) -> bool:
    users = load_users()
    if username in users:
        hashed_pw = users[username].encode()
        return bcrypt.checkpw(password.encode(), hashed_pw)
    return False

def create_user(username: str, password: str) -> bool:
    users = load_users()
    if username in users:
        return False  # utente già esistente
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    users[username] = hashed.decode()
    save_users(users)
    return True
