from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_public_config_exposes_only_support_contact():
    response = client.get("/api/public-config")
    assert response.status_code == 200
    assert response.json() == {"support_phone": "+91-011-47695000"}
    assert "api_key" not in response.text.lower()


def test_admin_requires_key():
    response = client.get("/api/admin/documents")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid admin credentials"


def test_admin_dashboard_requires_authentication_and_uses_http_only_session():
    with TestClient(app) as browser:
        redirect = browser.get("/admin", follow_redirects=False)
        assert redirect.status_code == 303
        assert redirect.headers["location"] == "/admin/login"

        login_page = browser.get("/admin/login")
        assert login_page.status_code == 200
        assert "Document Admin" in login_page.text
        assert 'type="password"' in login_page.text
        assert "test-admin-api-key-at-least-24" not in login_page.text

        denied = browser.post("/admin/login", data={"api_key": "wrong"}, follow_redirects=False)
        assert denied.status_code == 401
        assert "set-cookie" not in denied.headers
        assert browser.get("/admin", follow_redirects=False).status_code == 303

        authenticated = browser.post("/admin/login", data={"api_key": "test-admin-api-key-at-least-24"}, follow_redirects=False)
        assert authenticated.status_code == 303
        assert authenticated.headers["location"] == "/admin"
        cookie = authenticated.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=lax" in cookie

        dashboard = browser.get("/admin")
        assert dashboard.status_code == 200
        assert "Manage the private retrieval index" in dashboard.text
        assert "test-admin-api-key-at-least-24" not in dashboard.text

        # A browser session does not weaken the separately protected API.
        api_response = browser.get("/api/admin/documents")
        assert api_response.status_code == 401
        assert api_response.headers.get("content-type", "").startswith("application/json")

        logout = browser.post("/admin/logout", follow_redirects=False)
        assert logout.status_code == 303
        assert logout.headers["location"] == "/admin/login"
        assert "max-age=0" in logout.headers["set-cookie"].lower()
        assert browser.get("/admin", follow_redirects=False).status_code == 303


def test_chat_validation_hides_internal_details():
    response = client.post("/api/chat", json={"message": " "})
    assert response.status_code == 422
    assert "traceback" not in response.text.lower()


def test_lead_validation():
    response = client.post("/api/leads", json={"name": "A", "company": "B", "email": "bad", "phone": "x", "requirement": "hi"})
    assert response.status_code == 422


def test_static_interface():
    response = client.get("/")
    assert response.status_code == 200
    assert "Company Assistant" in response.text
    assert 'id="microphone"' in response.text
    assert 'value="en-IN"' in response.text
    assert 'value="hi-IN"' in response.text
    assert 'id="career-form"' in response.text
    assert 'name="resume"' in response.text
    assert 'id="problem-solved"' in response.text
    assert 'id="still-not-working"' in response.text
    assert 'id="request-callback"' in response.text
    assert 'id="call-support"' in response.text


def test_voice_implementation_is_browser_only():
    response = client.get("/app.js")
    assert response.status_code == 200
    script = response.text
    assert "webkitSpeechRecognition" in script
    assert "speechSynthesis" in script
    assert "recognition.start()" in script
    assert "/api/transcription" not in script
    assert "/api/tts" not in script


def test_career_application_rejects_unsupported_resume_before_database_write():
    response = client.post(
        "/api/careers/applications",
        data={
            "full_name": "Test Candidate",
            "email": "candidate@example.com",
            "phone": "+91 9999999999",
            "position": "General Application",
            "qualification": "Graduate",
            "experience_years": "2 years",
            "skills": "Python and SQL",
            "current_location": "Delhi",
            "notice_period": "30 days",
            "consent_to_contact": "true",
        },
        files={"resume": ("resume.exe", b"not-a-resume", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Resume must be a PDF or DOCX file"
