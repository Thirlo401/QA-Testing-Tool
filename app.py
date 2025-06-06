from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup
import os
import re
import json
from werkzeug.utils import secure_filename
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
import subprocess
import uuid

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'generated_scripts'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def crawl_website(url):
    """Crawl website using Playwright to handle dynamic content."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until='networkidle')
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            browser.close()
            
            elements = []
            interactive_selectors = ['input', 'button', 'a', 'form', 'select', 'textarea']
            attr_selectors = [
                '[role="button"]', '[role="checkbox"]', '[role="radio"]', '[role="tab"]',
                '[role="menuitem"]', '[role="switch"]', '[data-testid]', '[data-cy]',
                '[data-test]', '[data-automation-id]', '[aria-label]'
            ]
            
            for selector in interactive_selectors:
                for element in soup.find_all(selector):
                    elem_data = extract_element_data(element, soup)
                    elements.append(elem_data)
            
            for selector in attr_selectors:
                for element in soup.select(selector):
                    if element.name not in interactive_selectors:
                        elem_data = extract_element_data(element, soup)
                        elements.append(elem_data)
            
            page_title = soup.title.string if soup.title else "Unknown Page"
            return {'elements': elements, 'page_title': page_title, 'url': url}
    except Exception as e:
        print(f"Error crawling website: {str(e)}")
        return {'elements': [], 'page_title': "Error Page", 'url': url, 'error': str(e)}

def extract_element_data(element, soup):
    """Extract relevant data from an HTML element, including Livewire attributes."""
    class_list = element.get('class', [])
    class_str = ' '.join(class_list) if isinstance(class_list, list) else class_list
    text_content = ''
    if element.name not in ['input', 'textarea', 'select']:
        text_content = element.get_text().strip()
        if len(text_content) > 50:
            text_content = text_content[:50].strip() + "..."
        text_content = re.sub(r'\s+', ' ', text_content)
    
    wire_attrs = {k: element.get(k) for k in element.attrs if k.startswith('wire:')}
    
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
    """Generate a compound selector with uniqueness validation, selective :visible."""
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
    
    if selectors:
        compound = f"{element['tag']}{''.join(selectors[:2])}"
        if is_interactive:
            compound += ':visible'
        return validate_selector(compound, soup)
    
    if element.get('aria-label'):
        selector = f"[aria-label='{element['aria-label']}']"
        if is_interactive:
            selector += ':visible'
        return validate_selector(selector, soup)
    if element.get('placeholder'):
        escaped_placeholder = element.get('placeholder', '').replace("'", "\\'")
        selector = f"[placeholder='{escaped_placeholder}']"
        if is_interactive:
            selector += ':visible'
        return validate_selector(selector, soup)
    if element.get('text_content') and element['tag'] not in ['input', 'textarea', 'select']:
        text = element['text_content'].replace("'", "\\'")
        selector = f":contains('{text}')"
        return validate_selector(selector, soup)
    return element['xpath']

def generate_realistic_input_value(element):
    """Generate realistic test data based on input type."""
    input_type = element.get('type', '').lower()
    name = element.get('name', '').lower()
    placeholder = element.get('placeholder', '').lower()
    
    if any(term in name or term coqu in placeholder for term in ['email', 'e-mail']):
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
    """Generate a page object class for Cypress tests."""
    page_name = url_data['page_title'].replace(' ', '')
    script = f"""// Page Object for {url_data['page_title']}
// Encapsulates selectors and actions for maintainability

class {page_name}Page {{
  visit() {{
    cy.visit('{url_data['url']}', {{ retryOnStatusCodeFailure: true }});
    cy.get('[wire\\\\:loading]').should('not.exist'); // Wait for Livewire
  }}

  getElement(selector) {{
    return cy.get(selector);
  }}

  login(email, password) {{
    this.getElement('form').within(() => {{
      this.getElement('[type="email"]').type(email, {{ delay: 50 }});
      this.getElement('[type="password"]').type(password, {{ delay: 50 }});
      this.getElement('[type="submit"]').click();
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
    """Generate a Cypress test script with enhanced tests and structure."""
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
        data = request.json
        url = data.get('url')
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        url_data = crawl_website(url)
        if not url_data['elements']:
            return jsonify({
                'error': 'No testable elements found',
                'details': url_data.get('error', 'The page might be using client-side rendering or blocking crawlers')
            }), 400
        
        # Generate page object
        page_script = generate_page_object(url_data)
        page_filename = secure_filename(f"{url_data['page_title'].replace(' ', '')}Page.js")
        page_filepath = os.path.join(app.config['UPLOAD_FOLDER'], page_filename)
        with open(page_filepath, 'w') as f:
            f.write(page_script)
        
        # Generate fixture
        fixture_data = generate_fixture_data()
        fixture_filename = 'test_data.json'
        fixture_filepath = os.path.join(app.config['UPLOAD_FOLDER'], fixture_filename)
        with open(fixture_filepath, 'w') as f:
            json.dump(fixture_data, f)
        
        # Generate Cypress script
        soup = BeautifulSoup(requests.get(url).text, 'html.parser')  # For selector validation
        script = generate_cypress_script(url_data, soup)
        
        # Lint the script
        temp_filename = f"temp_{uuid.uuid4()}.js"
        temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)
        with open(temp_filepath, 'w') as f:
            f.write(script)
        result = subprocess.run(['eslint', temp_filepath], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Linting errors: {result.stderr}")
        os.remove(temp_filepath)
        
        # Save the script
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
            'page_title': url_data['page_title']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
