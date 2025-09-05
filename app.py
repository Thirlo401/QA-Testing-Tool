from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup
import os
import re
import json
from werkzeug.utils import secure_filename
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import subprocess
import uuid
from openai import OpenAI
from typing import Dict, List, Optional, Any

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'generated_scripts'
app.config['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY', '')  # Set your OpenAI API key in environment


os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def get_ai_suggestions(element_data: Dict[str, Any], page_context: str) -> Dict[str, Any]:
    """Get AI-powered suggestions for test strategies and assertions."""
    try:
        if not app.config['OPENAI_API_KEY']:
            return {}
            
        client = OpenAI(api_key=app.config['OPENAI_API_KEY'])
        prompt = f"""Given this web element data and page context, suggest optimal Cypress test strategies:
        Element: {json.dumps(element_data)}
        Page Context: {page_context}
        
        Provide suggestions for:
        1. Best selectors to use
        2. Recommended assertions
        3. Potential edge cases to test
        4. Performance considerations
        
        Return the response as a valid JSON object with these keys:
        - selectors: array of recommended selectors
        - assertions: array of recommended assertions
        - edge_cases: array of potential edge cases
        - performance: array of performance considerations
        """
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        
        if not response.choices or not response.choices[0].message:
            return {}
            
        try:
            suggestions = response.choices[0].message.content
            return json.loads(suggestions) if suggestions else {}
        except json.JSONDecodeError:
            print("Failed to parse AI response as JSON")
            return {}
            
    except Exception as e:
        print(f"AI suggestion error: {str(e)}")
        return {}

def crawl_website(url: str) -> Dict[str, Any]:
    """Crawl website using Playwright with enhanced error handling and retries."""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                )
                page = context.new_page()

                # Set timeout and wait for network idle
                page.set_default_timeout(30000)
                page.goto(url, wait_until='networkidle')

                # Wait for dynamic content
                page.wait_for_load_state('domcontentloaded')
                page.wait_for_load_state('networkidle')

                html = page.content()
                soup = BeautifulSoup(html, 'html.parser')

                # Get page metadata
                page_title = soup.title.string if soup.title else "Unknown Page"
                meta_description = soup.find('meta', {'name': 'description'})
                description = meta_description['content'] if meta_description else ""

                elements = []
                interactive_selectors = ['input', 'button', 'a', 'form', 'select', 'textarea']
                attr_selectors = [
                    '[role="button"]', '[role="checkbox"]', '[role="radio"]', '[role="tab"]',
                    '[role="menuitem"]', '[role="switch"]', '[data-testid]', '[data-cy]',
                    '[data-test]', '[data-automation-id]', '[aria-label]'
                ]

                # Extract elements with enhanced data
                for selector in interactive_selectors:
                    for element in soup.find_all(selector):
                        elem_data = extract_element_data(element, soup)
                        ai_suggestions = get_ai_suggestions(elem_data, f"Page: {page_title}, Description: {description}")
                        elem_data['ai_suggestions'] = ai_suggestions
                        elements.append(elem_data)

                for selector in attr_selectors:
                    for element in soup.select(selector):
                        if element.name not in interactive_selectors:
                            elem_data = extract_element_data(element, soup)
                            ai_suggestions = get_ai_suggestions(elem_data, f"Page: {page_title}, Description: {description}")
                            elem_data['ai_suggestions'] = ai_suggestions
                            elements.append(elem_data)

                browser.close()
                return {
                    'elements': elements,
                    'page_title': page_title,
                    'description': description,
                    'url': url
                }

        except PlaywrightTimeoutError:
            retry_count += 1
            if retry_count == max_retries:
                return {'error': 'Page load timeout after multiple retries', 'elements': []}
            continue
        except Exception as e:
            return {'error': str(e), 'elements': []}
    
    return {'error': 'Failed to crawl website after retries', 'elements': []}

def extract_element_data(element, soup):
    """Extract relevant data from an HTML element, including labels and Livewire attributes."""
    class_list = element.get('class', [])
    class_str = ' '.join(class_list) if isinstance(class_list, list) else class_list
    text_content = ''
    if element.name not in ['input', 'textarea', 'select']:
        text_content = element.get_text().strip()
        if len(text_content) > 50:
            text_content = text_content[:50].strip() + "..."
        text_content = re.sub(r'\s+', ' ', text_content)

    # Attempt to find an associated label
    label_text = ''
    elem_id = element.get('id')
    if elem_id:
        label = soup.find('label', attrs={'for': elem_id})
        if label:
            label_text = re.sub(r'\s+', ' ', label.get_text(strip=True))
    if not label_text:
        parent_label = element.find_parent('label')
        if parent_label:
            label_text = re.sub(r'\s+', ' ', parent_label.get_text(strip=True))

    wire_attrs = {k: element.get(k) for k in element.attrs if k.startswith('wire:')}

    # Capture select options
    options = []
    if element.name == 'select':
        for opt in element.find_all('option'):
            options.append({
                'text': re.sub(r'\s+', ' ', opt.get_text(strip=True)),
                'value': opt.get('value', '')
            })

    return {
        'tag': element.name,
        'id': element.get('id', ''),
        'class': class_str,
        'type': element.get('type', ''),
        'name': element.get('name', ''),
        'placeholder': element.get('placeholder', ''),
        'value': element.get('value', ''),
        'href': element.get('href', ''),
        'role': element.get('role', ''),
        'aria-label': element.get('aria-label', ''),
        'data-testid': element.get('data-testid', ''),
        'data-cy': element.get('data-cy', ''),
        'data-test': element.get('data-test', ''),
        'data-automation-id': element.get('data-automation-id', ''),
        'text_content': text_content,
        'label': label_text,
        'options': options,
        'visible': True,
        'xpath': get_xpath(element),
        'required': element.has_attr('required'),
        **wire_attrs
    }

def get_xpath(element):
    """Calculate a simple XPath for an element."""
    components = []
    child = element
    for parent in element.parents:
        if parent.name == 'html':
            break
        siblings = parent.find_all(child.name, recursive=False)
        if len(siblings) > 1:
            index = siblings.index(child) + 1
            components.append(f"{child.name}[{index}]")
        else:
            components.append(child.name)
        child = parent
    components.reverse()
    return f"//{'/'.join(components)}" if components else f"//{element.name}"

def validate_selector(selector, soup):
    """Validate selector uniqueness, escaping :visible for BeautifulSoup."""
    # Escape :visible for BeautifulSoup parsing
    bs_selector = selector.replace(':visible', '\\:visible')
    try:
        matches = soup.select(bs_selector)
        if len(matches) > 1:
            return f"{selector}:nth-of-type(1)"
        return selector
    except Exception:
        # Fallback to original selector if parsing fails
        return selector

def get_best_selector(element, soup):
    """Generate a robust selector with uniqueness validation, prioritizing stable attributes."""
    selectors = []
    is_interactive = element['tag'] in ['input', 'button', 'form', 'select', 'textarea'] or element.get('role') in ['button', 'checkbox', 'radio']
    
    if element.get('data-testid'):
        selectors.append(f"[data-testid='{element['data-testid']}']")
    if element.get('data-cy'):
        selectors.append(f"[data-cy='{element['data-cy']}']")
    if element.get('data-test'):
        selectors.append(f"[data-test='{element['data-test']}']")
    if element.get('data-automation-id'):
        selectors.append(f"[data-automation-id='{element['data-automation-id']}']")
    if element.get('wire:model'):
        selectors.append(f"[wire\\\\:model='{element['wire:model']}']")
    if element.get('id'):
        selectors.append(f"#{element['id']}")
    if element.get('name'):
        selectors.append(f"[name='{element['name']}']")
    if element.get('aria-label'):
        selectors.append(f"[aria-label='{element['aria-label']}']")
    
    if selectors:
        compound = f"{element['tag']}{''.join(selectors[:2])}"
        if is_interactive:
            compound += ':visible'
        return validate_selector(compound, soup)
    
    if element.get('placeholder'):
        placeholder_escaped = element['placeholder'].replace("'", "\\'")
        selector = f"[placeholder='{placeholder_escaped}']"
        if is_interactive:
            selector += ':visible'
        return validate_selector(selector, soup)
    return element['xpath']

def generate_realistic_input_value(element):
    """Generate realistic test data based on input type."""
    input_type = element.get('type', '').lower()
    name = element.get('name', '').lower()
    placeholder = element.get('placeholder', '').lower()
    
    if any(term in name or term in placeholder for term in ['email', 'e-mail']):
        return 'test.user@example.com'
    elif any(term in name or term in placeholder for term in ['password', 'pwd']):
        return 'TestPassword123!'
    elif any(term in name or term in placeholder for term in ['username', 'user', 'login']):
        return 'testuser2025'
    elif any(term in name or term in placeholder for term in ['phone', 'mobile', 'tel']):
        return '555-123-4567'
    elif input_type == 'email':
        return 'test.user@example.com'
    elif input_type == 'password':
        return 'TestPassword123!'
    elif input_type == 'number':
        return '42'
    else:
        return 'Test Input Value'

def generate_page_object(url_data):
    """Generate a page object class for Cypress tests with practical helpers."""
    page_name = url_data['page_title'].replace(' ', '')
    script = f"""// Page Object for {url_data['page_title']}
// Encapsulates selectors and actions for maintainability

class {page_name}Page {{
  visit() {{
    cy.visit('{url_data['url']}');
  }}

  get(selector) {{
    return cy.get(selector);
  }}

  type(selector, value) {{
    this.get(selector).clear().type(value);
  }}

  select(selector, valueOrText) {{
    this.get(selector).select(valueOrText);
  }}

  check(selector) {{
    this.get(selector).check({{ force: true }});
  }}

  click(selector) {{
    this.get(selector).click();
  }}

  login(email, password) {{
    this.get('form').within(() => {{
      this.type('[type="email"]', email);
      this.type('[type="password"]', password);
      this.click('[type="submit"]');
    }});
  }}
}}

module.exports = {page_name}Page;
"""
    return script

def generate_fixture_data():
    """Generate a JSON fixture file for test data."""
    return {
        'users': [
            {'email': 'test.user@example.com', 'password': 'TestPassword123!'},
            {'email': 'invalid.user@example.com', 'password': 'WrongPass123!'}
        ]
    }

def generate_cypress_script(url_data, soup):
    """Generate a Cypress test script with enhanced tests and structure following docs."""
    url = url_data['url']
    elements = url_data['elements']
    page_title = url_data['page_title'].strip()
    domain = urlparse(url).netloc
    page_name = page_title.replace(' ', '')

    script = f"""// {page_title} Test Suite for {domain}
// Generated on: {url}
// Purpose: Smoke, E2E, authentication, and Livewire tests
// Note: Uses page object model and fixtures for maintainability
// Requires: npm install cypress mochawesome cypress-wait-until

const {page_name}Page = require('./{page_name}Page');

Cypress.config('defaultCommandTimeout', 10000);
Cypress.config('pageLoadTimeout', 30000);

describe('{page_title} - Automated Test Suite', () => {{
  const page = new {page_name}Page();

  before(() => {{
    // Load test data from fixtures
    cy.fixture('test_data.json').as('testData');
  }});

  beforeEach(() => {{
    // Visit page and wait for Livewire to load
    page.visit();
    cy.window().should('have.property', 'document.readyState', 'complete');
    cy.get('body').should('be.visible');
    cy.intercept('POST', '**/_livewire**').as('livewireUpdate');
  }});

  describe('Smoke Tests', () => {{
    it('loads the page successfully', () => {{
      // Verifies page loads and is interactable
      cy.url().should('eq', '{url}');
      cy.title().should('not.be.empty');
      page.getElement('body').should('be.visible');
      cy.on('uncaught:exception', (err) => {{
        cy.log(`Unhandled exception: ${{err.message}}`);
        return false;
      }});
    }});
  }});

  describe('End-to-End Tests', () => {{
"""
    # Form submission test
    forms = [e for e in elements if e['tag'] == 'form']
    inputs = [e for e in elements if e['tag'] == 'input']
    buttons = [e for e in elements if e['tag'] == 'button' or e['role'] == 'button']

    if forms:
        form = forms[0]
        form_selector = get_best_selector(form, soup)
        form_fields = [e for e in inputs if e.get('form') == form.get('id') or not e.get('form')]
        submit_button = next((b for b in buttons if 'submit' in b.get('type', '').lower()), None)

        script += f"""
    it('completes a Livewire form submission', () => {{
      // Fills and submits a form, verifying Livewire update
      // Assumes success message or redirect on submission
      page.getElement('{form_selector}').should('exist').within(() => {{
"""
        for field in form_fields:
            wire_model = field.get('wire:model', '')
            field_selector = f"[wire\\\\:model='{wire_model}']" if wire_model else get_best_selector(field, soup)
            test_value = generate_realistic_input_value(field)
            if field['type'] not in ['submit', 'button', 'hidden'] and not field['name'].startswith('_'):
                script += f"""        page.getElement('{field_selector}')
          .type('{test_value}', {{ delay: 50 }})
          .should('have.value', '{test_value}');
"""
        if submit_button:
            submit_selector = get_best_selector(submit_button, soup)
            script += f"""        page.getElement('{submit_selector}').click();
      }});
      cy.wait('@livewireUpdate').its('response.statusCode').should('eq', 200);
      cy.get('body').should('contain', 'success'); // Adjust based on response
    }});
"""

    # Authentication tests
    login_form = next((f for f in forms if any('email' in i.get('name', '').lower() or i['type'] == 'email' for i in inputs)), None)
    if login_form:
        script += f"""
    it('tests login with valid credentials', function() {{
      // Tests successful login using fixture data
      // Assumes redirect to dashboard on success
      page.login(this.testData.users[0].email, this.testData.users[0].password);
      cy.wait('@livewireUpdate');
      cy.url().should('include', '/dashboard'); // Adjust based on redirect
      cy.contains(this.testData.users[0].email); // Verify user data
    }});

    it('tests login with invalid credentials', function() {{
      // Tests login failure with invalid credentials
      // Assumes error message is displayed
      page.login(this.testData.users[1].email, this.testData.users[1].password);
      cy.wait('@livewireUpdate');
      cy.contains('Invalid credentials'); // Adjust based on error message
    }});
"""

    # Error handling test
    required_fields = [e for e in elements if e.get('required')]
    if required_fields:
        field = required_fields[0]
        field_selector = get_best_selector(field, soup)
        script += f"""
    it('validates required field', () => {{
      // Tests form validation for required field
      // Assumes error class or message on validation failure
      page.getElement('{field_selector}').clear();
      page.getElement('form').submit();
      page.getElement('{field_selector}').should('have.class', 'error'); // Adjust based on validation
    }});
"""

    # Livewire state test
    livewire_elements = [e for e in elements if e.get('wire:model')]
    if livewire_elements:
        element = livewire_elements[0]
        selector = f"[wire\\\\:model='{element['wire:model']}']"
        test_value = generate_realistic_input_value(element)
        script += f"""
    it('verifies Livewire state update', () => {{
      // Tests Livewire component state update
      // Verifies input value persists after Livewire update
      page.getElement('{selector}').type('{test_value}', {{ delay: 50 }});
      cy.wait('@livewireUpdate');
      page.getElement('{selector}').should('have.value', '{test_value}');
    }});
"""

    script += """
  });
}});
"""
    return script

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/generate', methods=['POST'])
def generate_script():
    try:
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400
            
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON data'}), 400
            
        url = data.get('url')
        if not url:
            return jsonify({'error': 'URL is required'}), 400
            
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        url_data = crawl_website(url)
        if 'error' in url_data:
            return jsonify({
                'error': 'Failed to crawl website',
                'details': url_data['error']
            }), 400
            
        if not url_data['elements']:
            return jsonify({
                'error': 'No testable elements found',
                'details': 'The page might be using client-side rendering or blocking crawlers'
            }), 400
        
        # Generate page object with AI-enhanced selectors
        page_script = generate_page_object(url_data)
        page_filename = secure_filename(f"{url_data['page_title'].replace(' ', '')}Page.js")
        page_filepath = os.path.join(app.config['UPLOAD_FOLDER'], page_filename)
        
        with open(page_filepath, 'w') as f:
            f.write(page_script)
        
        # Generate fixture with AI-suggested test data
        fixture_data = generate_fixture_data()
        fixture_filename = 'test_data.json'
        fixture_filepath = os.path.join(app.config['UPLOAD_FOLDER'], fixture_filename)
        
        with open(fixture_filepath, 'w') as f:
            json.dump(fixture_data, f, indent=2)
        
        # Generate Cypress script with AI-enhanced tests
        soup = BeautifulSoup(requests.get(url, timeout=30).text, 'html.parser')
        script = generate_cypress_script(url_data, soup)
        
        # Lint the script with ESLint
        temp_filename = f"temp_{uuid.uuid4()}.js"
        temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)
        
        with open(temp_filepath, 'w') as f:
            f.write(script)
            
        result = subprocess.run(
            ['eslint', '--fix', temp_filepath],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"Linting errors: {result.stderr}")
            # Try to fix common linting issues
            script = fix_common_linting_issues(script)
        
        os.remove(temp_filepath)
        
        # Save the final script
        domain = urlparse(url).netloc.replace('.', '_')
        filename = secure_filename(f"cypress_test_{domain}.js")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        with open(filepath, 'w') as f:
            f.write(script)
        
        return jsonify({
            'script': script,
            'page_object': page_script,
            'fixture': fixture_data,
            'filename': filename,
            'page_filename': page_filename,
            'fixture_filename': fixture_filename,
            'element_count': len(url_data['elements']),
            'page_title': url_data['page_title'],
            'ai_enhanced': True
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def fix_common_linting_issues(script: str) -> str:
    """Fix common ESLint issues in the generated script."""
    fixes = {
        'no-unused-vars': lambda s: re.sub(r'const\s+(\w+)\s*=\s*[^;]+;\s*(?!.*\1)', '', s),
        'no-console': lambda s: re.sub(r'console\.log\([^)]+\);', '', s),
        'semi': lambda s: re.sub(r'([^;])\n', r'\1;\n', s)
    }
    
    for fix in fixes.values():
        script = fix(script)
    
    return script

@app.route('/api/test_types', methods=['GET'])
def get_test_types():
    """Return the types of tests that can be generated."""
    return jsonify({
        'test_types': [
            {'id': 'basic', 'name': 'Basic Page Tests', 'description': 'Tests that the page loads and basic elements are visible'},
            {'id': 'interactive', 'name': 'Interactive Element Tests', 'description': 'Tests for forms, buttons, and inputs'},
            {'id': 'auth', 'name': 'Authentication Tests', 'description': 'Tests for login flows'},
            {'id': 'validation', 'name': 'Validation Tests', 'description': 'Tests for form validation'}
        ]
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
