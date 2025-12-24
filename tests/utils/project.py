import uuid

from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import Project, ProjectCreate
from tests.utils.user import create_random_user
from tests.utils.utils import random_lower_string


def create_random_project(db: Session, owner_id: uuid.UUID | None = None) -> Project:
    """Create a random project for testing.

    Args:
        db: Database session
        owner_id: Owner user ID. If not provided, creates a new random user.
    """
    if owner_id is None:
        user = create_random_user(db)
        owner_id = user.id
    assert owner_id is not None
    name = f"Project {random_lower_string()}"
    seed_url = f"https://{random_lower_string()}.com"
    description = random_lower_string()
    project_in = ProjectCreate(
        name=name,
        seed_url=seed_url,
        description=description,
    )
    return crud.create_project(session=db, project_in=project_in, owner_id=owner_id)
