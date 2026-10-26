"""Supply displayed revisions for existing tests of otherwise-valid commands.

Tests of missing/stale preconditions disable this helper or supply a literal
If-Match header. Production clients must use their displayed snapshot instead.
"""


def include_displayed_revision(client, publishing):
    def revision(request):
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"} \
                or not request.url.path.startswith("/api/packages/active/") \
                or "if-match" in request.headers:
            return
        package = publishing.get_active_package()
        state = publishing._packages.read_package_state(package.id) if package else None
        package_id = package.id if package else 1
        version = state.content_revision if state else 1
        request.headers["If-Match"] = f'"{package_id}:{version}"'
    client.event_hooks["request"].append(revision)
