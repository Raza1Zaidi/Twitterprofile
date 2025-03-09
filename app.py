import json
import time
import random
import gzip
import csv
import os
import subprocess
from flask import Flask, request, render_template_string
from seleniumwire import webdriver  # Import from seleniumwire
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service  # Import Service for Selenium 4
from webdriver_manager.chrome import ChromeDriverManager

# --- Install Chrome and Chromedriver on Render (Linux) ---
def install_chrome():
    if not os.path.exists("/usr/bin/google-chrome"):
        print("Installing Chrome...")
        subprocess.run([
            "wget", "-q", "-O", "/tmp/chrome.deb",
            "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"
        ])
        subprocess.run(["apt", "install", "-y", "/tmp/chrome.deb"])
    else:
        print("Chrome is already installed.")

install_chrome()

# Run the installation (for Render deployment)
install_chrome()

# --- Selenium Functions ---
def init_driver():
    chrome_options = webdriver.ChromeOptions()
    
    # Use headless mode for Render
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Specify the correct Chrome binary location
    chrome_options.binary_location = "/usr/bin/google-chrome"

    # Use webdriver_manager to auto-download ChromeDriver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    return driver

def fetch_profile_metrics(driver, screen_name):
    """
    Navigate to the Twitter profile page, wait for network requests,
    and intercept the GraphQL request by its unique endpoint identifier.
    """
    url = f"https://x.com/{screen_name}"
    print(f"\nNavigating to {url}")
    driver.get(url)
    time.sleep(random.uniform(3, 6))
    
    target_request = None
    for request in driver.requests:
        if request.response and "UserByScreenName" in request.url and screen_name.lower() in request.url.lower():
            target_request = request
            break

    if target_request:
        try:
            raw_body = target_request.response.body
            try:
                body = raw_body.decode('utf-8')
            except UnicodeDecodeError:
                body = gzip.decompress(raw_body).decode('utf-8')
                
            data = json.loads(body)
            # Try to get legacy metrics from possible nesting
            legacy = data.get("data", {}).get("user", {}).get("result", {}).get("legacy", {})
            if not legacy:
                legacy = data.get("data", {}).get("user", {}).get("legacy", {})
            
            metrics = {
                "followers_count": legacy.get("followers_count"),
                "friends_count": legacy.get("friends_count"),
                "listed_count": legacy.get("listed_count"),
                "location": legacy.get("location")
            }
            print(f"Metrics for {screen_name}: {metrics}")
            return metrics
        except Exception as e:
            print(f"Error parsing response for {screen_name}: {e}")
            return None
    else:
        print(f"No matching network request found for {screen_name}")
        return None

# --- Flask Application ---
app = Flask(__name__)

# Inline HTML template
template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Twitter Scraper</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .container { max-width: 800px; margin: auto; }
        input[type=text] { width: 100%; padding: 10px; margin: 5px 0 15px; }
        button { padding: 10px 20px; font-size: 16px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { padding: 8px; border: 1px solid #ccc; text-align: left; }
        th { background-color: #f2f2f2; }
    </style>
</head>
<body>
<div class="container">
    <h2>Twitter Profile Scraper</h2>
    <form method="POST">
        <label for="auth_token">Auth Token:</label>
        <input type="text" id="auth_token" name="auth_token" required>
        
        <label for="ct0">CT0 Token:</label>
        <input type="text" id="ct0" name="ct0" required>
        
        <label for="profiles">Twitter Profiles (comma separated):</label>
        <input type="text" id="profiles" name="profiles" required>
        
        <button type="submit">Start Scraping</button>
    </form>
    {% if results %}
    <h3>Results:</h3>
    <table>
        <tr>
            <th>Screen Name</th>
            <th>Followers Count</th>
            <th>Friends Count</th>
            <th>Listed Count</th>
            <th>Location</th>
        </tr>
        {% for screen_name, metrics in results.items() %}
        <tr>
            <td>{{ screen_name }}</td>
            <td>{{ metrics.followers_count if metrics.followers_count is not none else "N/A" }}</td>
            <td>{{ metrics.friends_count if metrics.friends_count is not none else "N/A" }}</td>
            <td>{{ metrics.listed_count if metrics.listed_count is not none else "N/A" }}</td>
            <td>{{ metrics.location if metrics.location else "N/A" }}</td>
        </tr>
        {% endfor %}
    </table>
    {% endif %}
</div>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    results = None
    if request.method == "POST":
        auth_token = request.form.get("auth_token")
        ct0 = request.form.get("ct0")
        profiles = request.form.get("profiles")
        
        if not auth_token or not ct0 or not profiles:
            return "All fields are required!", 400
        
        screen_names = [name.strip() for name in profiles.split(",") if name.strip()]
        
        driver = init_driver()
        # Visit base URL to allow cookie injection
        driver.get("https://x.com")
        time.sleep(3)
        
        # Inject cookies
        driver.add_cookie({"name": "auth_token", "value": auth_token, "domain": ".x.com"})
        driver.add_cookie({"name": "ct0", "value": ct0, "domain": ".x.com"})
        
        results = {}
        for screen_name in screen_names:
            driver.requests.clear()
            metrics = fetch_profile_metrics(driver, screen_name)
            if metrics:
                results[screen_name] = metrics
            time.sleep(random.uniform(5, 10))
        
        driver.quit()
        
        # Optionally, save results as CSV (this file will be stored on the server)
        csv_filename = "results.csv"
        with open(csv_filename, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["screen_name", "followers_count", "friends_count", "listed_count", "location"])
            for screen_name, metrics in results.items():
                writer.writerow([
                    screen_name,
                    metrics.get("followers_count", ""),
                    metrics.get("friends_count", ""),
                    metrics.get("listed_count", ""),
                    metrics.get("location", "")
                ])
        print(f"CSV file saved as {csv_filename}")
        
    return render_template_string(template, results=results)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
