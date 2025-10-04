# # database.py
# from databases import Database
# from sqlalchemy import create_engine, MetaData

# # Define the database file
# DATABASE_URL = "sqlite:///./lab_assistant.db"

# # Create the core database objects
# database = Database(DATABASE_URL)
# metadata = MetaData()
# engine = create_engine(DATABASE_URL)

# database.py
from databases import Database
from sqlalchemy import create_engine, MetaData
import os
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env for local development

# This will use the cloud database URL when deployed, or your local one if you set it
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lab_assistant.db")

# Create the core database objects
database = Database(DATABASE_URL)
metadata = MetaData()
engine = create_engine(DATABASE_URL)