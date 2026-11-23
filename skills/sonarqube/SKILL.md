---
name: sonarqube
description: "Start SonarQube in Docker, analyze the code and propose improvements. Triggers: статический анализ, технический долг, code smells, покрытие, автоматизированное качество."
disable-model-invocation: true
---

# Quality analysis with SonarQube

Communicate with the user in Russian.

## Summary

Start a SonarQube instance in Docker, analyze the project code and turn the results into actionable improvements. SonarQube finds bugs, vulnerabilities, code smells and coverage gaps that linters miss.

It does not replace qa-engineer or security-officer. It adds an automated second opinion based on static rules.

## Process

### Step 1: Docker and permission preflight

Check that Docker is available and the daemon responds:

```bash
docker --version
docker info
```

Interpret the result:

- **If `docker --version` fails**: Docker is not installed. Tell the user that SonarQube needs it and that installation can require administrator rights.
- **If `docker --version` works but `docker info` fails**: Docker is installed but the daemon is not available. Tell the user to start Docker Desktop or the system service before you continue.

**Do not install Docker, open Docker Desktop or start the daemon without explicit user approval.** If the command came from `/alfred audit`, follow the decision made in its preflight. If there is no prior permission, ask for it now and wait for the answer.

If the user allows installation, install the latest stable version for their platform:

**macOS:**
```bash
brew install --cask docker
open -a Docker
```

**Linux (Ubuntu/Debian):**
```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl start docker
sudo usermod -aG docker $USER
```

**Windows (PowerShell as administrator):**
```powershell
winget install Docker.DockerDesktop
```

If the user allows starting Docker when it is installed but the daemon does not respond, use the minimal strategy for the platform:

**macOS:**
```bash
open -a Docker
```

**Linux (systemd):**
```bash
sudo systemctl start docker
```

**Windows (PowerShell):**
```powershell
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
```

After you install or start Docker, check again with `docker info`.

- If `docker info` responds correctly, continue.
- If the user declined installation or start, or the daemon still does not respond, **stop the SonarQube branch here** and return an explicit result: «SonarQube пропущен по решению пользователя или из-за нехватки прав». Do not try to work around this.

### Step 2: Start SonarQube

Before you start the container:

- Check whether `sonarqube-alfred` exists. If it is left from a previous run, remove it first to avoid conflicts:

```bash
docker rm -f sonarqube-alfred 2>/dev/null || true
```

- Check whether port `9000` is in use. If it is, stop and ask the user whether to free the port or continue without SonarQube. Do not kill processes yourself.

```bash
docker run -d --name sonarqube-alfred -p 9000:9000 sonarqube:community
```

Wait until SonarQube is ready (can take 1-2 minutes):

Use exactly this loop or an equivalent. **Do not use the `status` variable in shell scripts**: in `zsh` it is read-only and breaks the wait. If you need to store the state in a variable, use `sonar_status`.

```bash
until curl -s http://localhost:9000/api/system/status | grep -q '"status":"UP"'; do sleep 5; done
```

Default credentials: admin/admin. Change the password at first login.

### Step 3: Configure the project

- Create the project in SonarQube (API or web UI).
- Generate an authentication token for the analysis.
- Create or check `sonar-project.properties` in the project root:

```properties
sonar.projectKey=my-project
sonar.sources=src
sonar.tests=tests
sonar.language=ts
sonar.sourceEncoding=UTF-8
```

Adapt it to the project stack (language, source and test directories).

### Step 4: Run the analysis

Node/TypeScript projects:

```bash
npx sonarqube-scanner
```

Python projects:

```bash
pip install pysonar-scanner && pysonar-scanner
```

Universal alternative with Docker:

```bash
docker run --rm -v "$(pwd):/usr/src" sonarsource/sonar-scanner-cli
```

### Step 5: Interpret the results

Open http://localhost:9000 and review the project dashboard. Classify findings by:

- **Bugs**: errors that can cause wrong behavior. High priority.
- **Vulnerabilities**: security issues found by OWASP/CWE rules. Notify security-officer.
- **Code smells**: maintainability issues. Prioritize those with the largest effect.
- **Coverage**: share of code covered by tests. Identify critical uncovered areas.

### Step 6: Produce the improvement report

Create a report with:

- Short summary: key metrics (bugs, vulnerabilities, coverage, technical debt).
- Top 10 findings by impact with a proposed fix.
- Code areas with the highest issue density.
- Comparison with the previous analysis, if one exists.

### Step 7: Clean up

When the analysis is done and the results are reviewed:

```bash
docker stop sonarqube-alfred && docker rm sonarqube-alfred
```

If the analysis failed midway, still try to do the final cleanup of the temporary container before you exit.

## Do NOT

- Do not leave SonarQube running. It is a one-time analysis tool, not a permanent service.
- Do not install Docker, start the daemon or open Docker Desktop without explicit user permission.
- Do not treat all findings as equal. Prioritize by real impact, not by count.
- Do not fix findings before you understand why SonarQube flags them. False positives happen.
- Do not replace human code reviews with SonarQube. They complement each other.

## Stack reference

Check the stack defined in the Alfred configuration to choose the right scanner (Node.js, Python, etc.) and configure `sonar-project.properties` with the correct language and directories.
