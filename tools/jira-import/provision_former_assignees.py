"""
Create Plane accounts for Jira assignees who had none, so their tickets can be
assigned to them (phase 3 does the assigning). Same approach as
provision_plane_users.py, but the password is passed in at run time and never
stored in this file or printed:

    docker exec -i -e PROVISION_PASSWORD='...' plane-app-api-1 \\
        python manage.py shell < provision_former_assignees.py

Safe to re-run: an existing account is never changed (no password reset); it is
only added to the workspace/projects if missing. No emails are sent.
"""

import os

from plane.db.models import Profile, Project, ProjectMember, ProjectUserProperty, User, Workspace, WorkspaceMember

WORKSPACE_SLUG = "lokko"
PROJECT_IDENTIFIERS = ["LOKKO", "TEST"]
MEMBER_ROLE = 15  # 20 = admin, 15 = member, 5 = guest

# (first name, last name, email) -- emails confirmed by the user on 2026-10-15
PEOPLE = [
    ("Derek Matthew", "Biju", "derek.biju@appymonkeys.com"),
    ("Lamminlun", "Simte", "laminlunn.simte@appymonkeys.com"),
    ("Projjal", "Chakrabarti", "projjal.chakrabarti@appymonkeys.com"),
    ("Prajwal", "K", "prajwal.k@appymonkeys.com"),
    ("Pavithrasri", "Poornachandran", "pavithrasri.poornachandran@appymonkeys.com"),
]

password = os.environ.get("PROVISION_PASSWORD")
if not password:
    raise SystemExit("PROVISION_PASSWORD is not set")

workspace = Workspace.objects.get(slug=WORKSPACE_SLUG)
projects = list(Project.objects.filter(workspace=workspace, identifier__in=PROJECT_IDENTIFIERS))
missing = set(PROJECT_IDENTIFIERS) - {p.identifier for p in projects}
if missing:
    raise SystemExit(f"Project(s) not found: {sorted(missing)}")

for first_name, last_name, email in PEOPLE:
    email = email.strip().lower()
    user = User.objects.filter(email=email).first()
    created = user is None
    if created:
        user = User(
            email=email,
            username=email.split("@")[0].replace(".", "_") + "_" + os.urandom(3).hex(),
            first_name=first_name,
            last_name=last_name,
            display_name=f"{first_name} {last_name}",
            is_active=True,
            is_email_verified=True,
        )
        user.set_password(password)
        user.is_password_autoset = False
        user.save()

    profile, _ = Profile.objects.get_or_create(user=user)
    if created:
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

    print(
        f"OK\t{email}\t{'account-created' if created else 'account-existing'}\t"
        f"workspace={'added' if ws_added else 'already'} projects_added={projects_added or '-'}"
    )
