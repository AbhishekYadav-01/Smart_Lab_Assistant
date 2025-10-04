# models.py
import sqlalchemy
from database import metadata

# Define the 'users' table
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("username", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("full_name", sqlalchemy.String),
    sqlalchemy.Column("email", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("hashed_password", sqlalchemy.String),
    sqlalchemy.Column("role", sqlalchemy.String, default="student"),
)

# Define the 'labs' table
labs = sqlalchemy.Table(
    "labs",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True),
    sqlalchemy.Column("capacity", sqlalchemy.Integer),
    sqlalchemy.Column("description", sqlalchemy.Text, nullable=True),
    sqlalchemy.Column("equipment", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("operating_start_time", sqlalchemy.Time, nullable=True),
    sqlalchemy.Column("operating_end_time", sqlalchemy.Time, nullable=True),
)

# Define the 'bookings' table
bookings = sqlalchemy.Table(
    "bookings",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("lab_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("labs.id")),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("start_time", sqlalchemy.DateTime),
    sqlalchemy.Column("end_time", sqlalchemy.DateTime),
    sqlalchemy.Column("student_count", sqlalchemy.Integer),
    sqlalchemy.Column("booked_by", sqlalchemy.String), # Keep username for easy access
    sqlalchemy.Column("priority", sqlalchemy.Integer, default=3), # Add priority with a default value
)