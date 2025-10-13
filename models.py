import sqlalchemy
from database import metadata

organizations = sqlalchemy.Table(
    "organizations",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("owner_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("required_email_domain", sqlalchemy.String, nullable=False),
)

users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("organization_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("organizations.id"), nullable=False),
    sqlalchemy.Column("username", sqlalchemy.String, index=True),
    sqlalchemy.Column("full_name", sqlalchemy.String),
    sqlalchemy.Column("email", sqlalchemy.String, index=True),
    sqlalchemy.Column("hashed_password", sqlalchemy.String),
    sqlalchemy.Column("role", sqlalchemy.String, default="student"),
    sqlalchemy.UniqueConstraint('username', 'organization_id', name='uq_user_org')
)

labs = sqlalchemy.Table(
    "labs",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("organization_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("organizations.id"), nullable=False),
    sqlalchemy.Column("name", sqlalchemy.String),
    sqlalchemy.Column("capacity", sqlalchemy.Integer),
    sqlalchemy.Column("description", sqlalchemy.Text, nullable=True),
    sqlalchemy.Column("equipment", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("operating_start_time", sqlalchemy.Time, nullable=True),
    sqlalchemy.Column("operating_end_time", sqlalchemy.Time, nullable=True),
    sqlalchemy.UniqueConstraint('name', 'organization_id', name='uq_lab_org')
)

bookings = sqlalchemy.Table(
    "bookings",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("organization_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("organizations.id"), nullable=False),
    sqlalchemy.Column("lab_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("labs.id")),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("start_time", sqlalchemy.DateTime(timezone=True)),
    sqlalchemy.Column("end_time", sqlalchemy.DateTime(timezone=True)),
    sqlalchemy.Column("student_count", sqlalchemy.Integer),
    sqlalchemy.Column("booked_by", sqlalchemy.String),
    sqlalchemy.Column("priority", sqlalchemy.Integer, default=3),
)