"""
Create Plane accounts for the people who appear in Jira, so imported tickets
can be assigned to / attributed to real users.

Run inside the API container through Django's shell (it uses Plane's models,
so passwords are hashed and profiles/memberships are created the way the app
expects):

    docker compose exec -T api python manage.py shell < provision_plane_users.py

Safe to re-run. Existing accounts are never modified (no password change);
they are only added to the workspace/projects if missing. New accounts get a
random temporary password, printed once on a `TEMP_PASSWORDS_JSON=` line --
capture that into a private file and hand the passwords out; don't log it.
"""

import json
import secrets
import uuid

from plane.db.models import (
    Profile,
    Project,
    ProjectMember,
    ProjectUserProperty,
    User,
    Workspace,
    WorkspaceMember,
)

WORKSPACE_SLUG = "lokko"
PROJECT_IDENTIFIERS = ["LOKKO", "TEST"]
MEMBER_ROLE = 15  # 20 = admin, 15 = member, 5 = guest

# (first name, last name, email)
PEOPLE = [
    ("Varun", "Sharma", "varun.sharma@appymonkeys.com"),
    ("Shashwat", "Bhatt", "shashwat.bhatt@appymonkeys.com"),
    ("Saket", "Palla", "saket@appymonkeys.com"),
    ("Satish", "Kumar", "satish.kumar@appymonkeys.com"),
    ("Shourish", "Adhicary", "shourish@appymonkeys.com"),
    ("Ranganath", "Pamisetty", "ranganath@appymonkeys.com"),
    ("Rohit", "Chaoji", "rohit.chaoji@appymonkeys.com"),
    ("Vidit", "Rawat", "vidit.rawat@appymonkeys.com"),
    ("Sonup", "Rimal", "sonup.rimal@appymonkeys.com"),
    ("Saji", "J", "saji.j@appymonkeys.com"),
    ("Nithin", "Suresh", "nithin.suresh@appymonkeys.com"),
    ("Kartikeya", "Chandrahas", "kc@appymonkeys.com"),
    ("Anurag", "Singh", "anurag.singh@appymonkeys.com"),
    ("Karthik", "Raghu", "karthik.raghu@appymonkeys.com"),
    ("A", "G", "angupte@gmail.com"),
    ("Pratik", "Sahoo", "pratik.sahoo@appymonkeys.com"),
    ("Ansh", "Kumar", "ansh@appymonkeys.com"),
]

workspace = Workspace.objects.get(slug=WORKSPACE_SLUG)
projects = list(Project.objects.filter(workspace=workspace, identifier__in=PROJECT_IDENTIFIERS))
missing = set(PROJECT_IDENTIFIERS) - {p.identifier for p in projects}
if missing:
    raise SystemExit(f"Project(s) not found: {sorted(missing)}")

temp_passwords = {}
summary = []

for first_name, last_name, email in PEOPLE:
    email = email.strip().lower()
    user = User.objects.filter(email=email).first()
    created = user is None
    if created:
        password = "Lk-" + secrets.token_urlsafe(9)
        user = User(
            email=email,
            username=uuid.uuid4().hex,
            first_name=first_name,
            last_name=last_name,
            is_active=True,
            is_email_verified=True,
        )
        user.set_password(password)
        user.is_password_autoset = False
        user.save()
        temp_passwords[email] = password

    profile, _ = Profile.objects.get_or_create(user=user)
    if created:
        # Skip the first-run onboarding screens and land them in the workspace.
        profile.is_onboarded = True
        profile.is_tour_completed = True
        profile.last_workspace_id = workspace.id
        if isinstance(profile.onboarding_step, dict):
            profile.onboarding_step = {key: True for key in profile.onboarding_step}
        profile.save()

    _, ws_added = WorkspaceMember.objects.get_or_create(
        workspace=workspace, member=user, defaults={"role": MEMBER_ROLE, "is_active": True}
    )
    projects_added = []
    for project in projects:
        _, added = ProjectMember.objects.get_or_create(
            workspace=workspace, project=project, member=user, defaults={"role": MEMBER_ROLE, "is_active": True}
        )
        ProjectUserProperty.objects.get_or_create(workspace=workspace, project=project, user=user)
        if added:
            projects_added.append(project.identifier)

    summary.append(
        f"{'CREATED ' if created else 'existing'} {email:36} "
        f"workspace={'added' if ws_added else 'already'} projects_added={projects_added or '-'}"
    )

print("PROVISION_SUMMARY_START")
for line in summary:
    print(line)
print("PROVISION_SUMMARY_END")
print("TEMP_PASSWORDS_JSON=" + json.dumps(temp_passwords))
