# database.py
from databases import Database
from sqlalchemy import create_engine, MetaData

# Define the database file
DATABASE_URL = "sqlite:///./lab_assistant.db"

# Create the core database objects
database = Database(DATABASE_URL)
metadata = MetaData()
engine = create_engine(DATABASE_URL)