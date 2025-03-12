from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import os
import re
import json
from urllib.parse import urlparse
import openai

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'generated_scripts'

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def crawl_website(url):
    """Crawl website and extract testable elements with AI reasoning."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        elements = []
        interactive_selectors = ['input', 'button', 'a', 'form', 'select', 'textarea']
        
        for selector in interactive_selectors:
            for element in soup.find_all(selector):
                elem_data = extract_element_data(element)
                elements.append(elem_data)

        page_title = soup.title.string if soup.title else "Unknown Page"
        return {'elements': elements, 'page_title': page_title, 'url': url}
    except Exception as e:
        return {'elements': [], 'page_title': "Error Page", 'url': url, 'error': str(e)}

def extract_element_data(element):
    """Extract relevant data from an HTML element."""
    return {
        'tag': element.name,
        'id': element.get('id', ''),
        'class': ' '.join(element.get('class', [])),
        'type': element.get('type', ''),
        'name': element.get('name', ''),
        'placeholder': element.get('placeholder', ''),
        'text_content': element.get_text(strip=True)[:50],
        'xpath': get_xpath(element)
    }

def get_xpath(element):
    """Generate XPath for an element."""
    components = []
    child = element
    for parent in element.parents:
        if parent.name == 'html':
            break
        siblings = parent.find_all(child.name, recursive=False)
        index = siblings.index(child) + 1 if len(siblings) > 1 else ''
        components.append(f"{child.name}{'[' + str(index) + ']' if index else ''}")
        child = parent
    components.reverse()
    return f"//{'/'.join(components)}"

def generate_cypress_script(url_data):
    """Generate Cypress script using AI for intelligent test coverage."""
    elements = url_data['elements']
    page_title = url_data['page_title']
    url = url_data['url']
    domain = urlparse(url).netloc

    prompt = f"""
    Generate a Cypress test script for the website '{page_title}' ({url}).
    Ensure intelligent interactions with the following elements:
    {json.dumps(elements, indent=2)}
    Use best practices to avoid flaky tests, include retries where needed, and use appropriate wait conditions.
    """
    
    ai_script = call_ai_for_cypress_script(prompt)
    return ai_script

def call_ai_for_cypress_script(prompt):
    """Use AI to generate a Cypress test script with enhanced stability."""
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=prompt,
        max_tokens=1500
    )
    return response['choices'][0]['text'].strip()

@app.route('/generate', methods=['POST'])
def generate_script():
    """API endpoint to generate a Cypress script."""
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({'error': 'Missing URL'}), 400
    
    url_data = crawl_website(url)
    script = generate_cypress_script(url_data)
    
    return jsonify({'script': script})

if __name__ == '__main__':
    app.run(debug=True)
