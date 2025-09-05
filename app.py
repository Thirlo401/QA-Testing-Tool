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
app.config['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY', '')

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

def detect_crud_operations(soup: BeautifulSoup, network_requests: List[Dict]) -> Dict[str, List[Dict]]:
    """Detect CRUD operations from HTML elements and network requests."""
    crud_operations = {
        'create': [],
        'read': [],
        'update': [],
        'delete': []
    }
    
    # Analyze forms for CRUD operations
    forms = soup.find_all('form')
    for form in forms:
        form_data = {
            'element': form,
            'method': form.get('method', 'get').lower(),
            'action': form.get('action', ''),
            'inputs': []
        }
        
        # Get all inputs in the form
        inputs = form.find_all(['input', 'textarea', 'select'])
        for inp in inputs:
            form_data['inputs'].append({
                'type': inp.get('type', ''),
                'name': inp.get('name', ''),
                'value': inp.get('value', ''),
                'required': inp.has_attr('required')
            })
        
        # Categorize based on method and action
        if form_data['method'] == 'post':
            action = form_data['action'].lower()
            if any(keyword in action for keyword in ['create', 'add', 'new', 'register', 'signup']):
                crud_operations['create'].append(form_data)
            elif any(keyword in action for keyword in ['edit', 'update', 'modify']):
                crud_operations['update'].append(form_data)
            elif any(keyword in action for keyword in ['delete', 'remove', 'destroy']):
                crud_operations['delete'].append(form_data)
            else:
                # Default POST forms to create if no clear indication
                crud_operations['create'].append(form_data)
        else:
            # GET forms are typically for search/read operations
            crud_operations['read'].append(form_data)
    
    # Analyze links for CRUD operations
    links = soup.find_all('a', href=True)
    for link in links:
        link_text = link.get_text().strip().lower()
        href = link.get('href', '').lower()
        
        link_data = {
            'element': link,
            'href': href,
            'text': link_text
        }
        
        if any(keyword in link_text or keyword in href for keyword in ['create', 'add', 'new']):
            crud_operations['create'].append(link_data)
        elif any(keyword in link_text or keyword in href for keyword in ['edit', 'update', 'modify']):
            crud_operations['update'].append(link_data)
        elif any(keyword in link_text or keyword in href for keyword in ['delete', 'remove', 'destroy']):
            crud_operations['delete'].append(link_data)
        elif any(keyword in link_text or keyword in href for keyword in ['view', 'show', 'details', 'list']):
            crud_operations['read'].append(link_data)
    
    # Analyze buttons for CRUD operations
    buttons = soup.find_all('button')
    for button in buttons:
        button_text = button.get_text().strip().lower()
        button_type = button.get('type', '').lower()
        onclick = button.get('onclick', '').lower()
        
        button_data = {
            'element': button,
            'text': button_text,
            'type': button_type,
            'onclick': onclick
        }
        
        if any(keyword in button_text or keyword in onclick for keyword in ['create', 'add', 'new', 'save']):
            crud_operations['create'].append(button_data)
        elif any(keyword in button_text or keyword in onclick for keyword in ['edit', 'update', 'modify']):
            crud_operations['update'].append(button_data)
        elif any(keyword in button_text or keyword in onclick for keyword in ['delete', 'remove', 'destroy']):
            crud_operations['delete'].append(button_data)
    
    # Analyze network requests for API-based CRUD operations
    for request in network_requests:
        method = request.get('method', '').upper()
        url = request.get('url', '').lower()
        
        request_data = {
            'method': method,
            'url': url,
            'headers': request.get('headers', {}),
            'body': request.get('body', '')
        }
        
        if method == 'POST' and '/api/' in url:
            if any(keyword in url for keyword in ['create', 'add', 'new']):
                crud_operations['create'].append(request_data)
            else:
                crud_operations['create'].append(request_data)
        elif method == 'GET' and '/api/' in url:
            crud_operations['read'].append(request_data)
        elif method in ['PUT', 'PATCH'] and '/api/' in url:
            crud_operations['update'].append(request_data)
        elif method == 'DELETE' and '/api/' in url:
            crud_operations['delete'].append(request_data)
    
    return crud_operations

def crawl_website_with_crud_detection(url: str) -> Dict[str, Any]:
    """Enhanced crawl function that detects CRUD operations."""
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
                
                # Capture network requests
                network_requests = []
                
                def handle_request(request):
                    network_requests.append({
                        'method': request.method,
                        'url': request.url,
                        'headers': dict(request.headers),
                        'post_data': request.post_data
                    })
                
                page.on('request', handle_request)
                
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
                
                # Extract elements (existing logic)
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
                
                # Detect CRUD operations
                crud_operations = detect_crud_operations(soup, network_requests)
                
                browser.close()
                return {
                    'elements': elements,
                    'page_title': page_title,
                    'description': description,
                    'url': url,
                    'crud_operations': crud_operations,
                    'network_requests': network_requests
                }
                
        except PlaywrightTimeoutError:
            retry_count += 1
            if retry_count == max_retries:
                return {'error': 'Page load timeout after multiple retries', 'elements': [], 'crud_operations': {}}
            continue
        except Exception as e:
            return {'error': str(e), 'elements': [], 'crud_operations': {}}
    
    return {'error': 'Failed to crawl website after retries', 'elements': [], 'crud_operations': {}}

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
    bs_selector = selector.replace(':visible', '\\:visible')
    try:
        matches = soup.select(bs_selector)
        if len(matches) > 1:
            return f"{selector}:nth-of-type(1)"
        return selector
    except Exception:
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

def generate_crud_tests(crud_operations: Dict[str, List[Dict]], soup: BeautifulSoup) -> str:
    """Generate Cypress tests for detected CRUD operations."""
    crud_tests = ""
    
    # Generate CREATE tests
    if crud_operations['create']:
        crud_tests += """
  describe('CREATE Operations', () => {
"""
        for i, operation in enumerate(crud_operations['create']):
            if 'element' in operation and hasattr(operation['element'], 'name'):
                element = operation['element']
                if element.name == 'form':
                    form_selector = get_best_selector({
                        'tag': element.name,
                        'id': element.get('id', ''),
                        'class': ' '.join(element.get('class', [])) if element.get('class') else '',
                        'action': element.get('action', ''),
                        'method': element.get('method', '')
                    }, soup)
                    
                    crud_tests += f"""
    it('should create new record via form {i+1}', () => {{
      cy.get('{form_selector}').should('be.visible').within(() => {{
        // Fill form fields with test data
"""
                    # Find inputs in the form
                    inputs = element.find_all(['input', 'textarea', 'select'])
                    for inp in inputs:
                        if inp.get('type') not in ['submit', 'button', 'hidden'] and inp.get('name'):
                            input_selector = get_best_selector({
                                'tag': inp.name,
                                'id': inp.get('id', ''),
                                'name': inp.get('name', ''),
                                'type': inp.get('type', ''),
                                'class': ' '.join(inp.get('class', [])) if inp.get('class') else ''
                            }, soup)
                            test_value = generate_realistic_input_value({
                                'type': inp.get('type', ''),
                                'name': inp.get('name', ''),
                                'placeholder': inp.get('placeholder', '')
                            })
                            
                            if inp.name == 'select':
                                crud_tests += f"""        cy.get('{input_selector}').select('{test_value}');
"""
                            else:
                                crud_tests += f"""        cy.get('{input_selector}').clear().type('{test_value}');
"""
                    
                    # Find submit button
                    submit_btn = element.find(['input[type="submit"]', 'button[type="submit"]', 'button'])
                    if submit_btn:
                        crud_tests += f"""        cy.get('[type="submit"]').click();
      }});
      
      // Verify creation success (adjust based on your app's behavior)
      cy.url().should('not.contain', '/create');
      cy.get('body').should('contain.text', 'success').or('contain.text', 'created');
    }});
"""
                elif element.name == 'a':
                    href = element.get('href', '')
                    text = element.get_text().strip()
                    crud_tests += f"""
    it('should navigate to create page via link "{text}"', () => {{
      cy.get('a[href*="{href}"]').click();
      cy.url().should('contain', '{href}');
      cy.get('form, [role="form"]').should('be.visible');
    }});
"""
        crud_tests += """  });
"""
    
    # Generate READ tests
    if crud_operations['read']:
        crud_tests += """
  describe('READ Operations', () => {
"""
        for i, operation in enumerate(crud_operations['read']):
            if 'element' in operation and hasattr(operation['element'], 'name'):
                element = operation['element']
                if element.name == 'a':
                    href = element.get('href', '')
                    text = element.get_text().strip()
                    crud_tests += f"""
    it('should read/view data via link "{text}"', () => {{
      cy.get('a[href*="{href}"]').click();
      cy.url().should('contain', '{href}');
      cy.get('body').should('be.visible');
      // Add specific assertions based on what data should be displayed
    }});
"""
        crud_tests += """  });
"""
    
    # Generate UPDATE tests
    if crud_operations['update']:
        crud_tests += """
  describe('UPDATE Operations', () => {
"""
        for i, operation in enumerate(crud_operations['update']):
            if 'element' in operation and hasattr(operation['element'], 'name'):
                element = operation['element']
                if element.name == 'form':
                    form_selector = get_best_selector({
                        'tag': element.name,
                        'id': element.get('id', ''),
                        'class': ' '.join(element.get('class', [])) if element.get('class') else '',
                        'action': element.get('action', ''),
                        'method': element.get('method', '')
                    }, soup)
                    
                    crud_tests += f"""
    it('should update existing record via form {i+1}', () => {{
      cy.get('{form_selector}').should('be.visible').within(() => {{
        // Update form fields with new test data
"""
                    inputs = element.find_all(['input', 'textarea', 'select'])
                    for inp in inputs:
                        if inp.get('type') not in ['submit', 'button', 'hidden'] and inp.get('name'):
                            input_selector = get_best_selector({
                                'tag': inp.name,
                                'id': inp.get('id', ''),
                                'name': inp.get('name', ''),
                                'type': inp.get('type', ''),
                                'class': ' '.join(inp.get('class', [])) if inp.get('class') else ''
                            }, soup)
                            test_value = f"Updated {generate_realistic_input_value({'type': inp.get('type', ''), 'name': inp.get('name', ''), 'placeholder': inp.get('placeholder', '')})}"
                            
                            if inp.name == 'select':
                                crud_tests += f"""        cy.get('{input_selector}').select('{test_value}');
"""
                            else:
                                crud_tests += f"""        cy.get('{input_selector}').clear().type('{test_value}');
"""
                    
                    crud_tests += f"""        cy.get('[type="submit"]').click();
      }});
      
      // Verify update success
      cy.get('body').should('contain.text', 'updated').or('contain.text', 'success');
    }});
"""
                elif element.name == 'a':
                    href = element.get('href', '')
                    text = element.get_text().strip()
                    crud_tests += f"""
    it('should navigate to edit page via link "{text}"', () => {{
      cy.get('a[href*="{href}"]').click();
      cy.url().should('contain', '{href}');
      cy.get('form, [role="form"]').should('be.visible');
    }});
"""
        crud_tests += """  });
"""
    
    # Generate DELETE tests
    if crud_operations['delete']:
        crud_tests += """
  describe('DELETE Operations', () => {
"""
        for i, operation in enumerate(crud_operations['delete']):
            if 'element' in operation and hasattr(operation['element'], 'name'):
                element = operation['element']
                if element.name == 'button':
                    button_text = element.get_text().strip()
                    crud_tests += f"""
    it('should delete record via button "{button_text}"', () => {{
      // First, ensure there's something to delete
      cy.get('body').should('be.visible');
      
      // Click delete button (may need confirmation)
      cy.get('button').contains('{button_text}').click();
      
      // Handle confirmation dialog if present
      cy.get('body').then(($body) => {{
        if ($body.find('[role="dialog"], .modal, .confirm').length > 0) {{
          cy.get('[role="dialog"] button, .modal button, .confirm button')
            .contains(/confirm|yes|delete|ok/i).click();
        }}
      }});
      
      // Verify deletion success
      cy.get('body').should('contain.text', 'deleted').or('contain.text', 'removed');
    }});
"""
                elif element.name == 'a':
                    href = element.get('href', '')
                    text = element.get_text().strip()
                    crud_tests += f"""
    it('should delete record via link "{text}"', () => {{
      cy.get('a[href*="{href}"]').click();
      
      // Handle confirmation if needed
      cy.get('body').then(($body) => {{
        if ($body.find('[role="dialog"], .modal, .confirm').length > 0) {{
          cy.get('[role="dialog"] button, .modal button, .confirm button')
            .contains(/confirm|yes|delete|ok/i).click();
        }}
      }});
      
      // Verify deletion success
      cy.get('body').should('contain.text', 'deleted').or('contain.text', 'removed');
    }});
"""
        crud_tests += """  });
"""
    
    return crud_tests

def generate_enhanced_cypress_script(url_data, soup):
    """Generate enhanced Cypress test script with CRUD operation tests."""
    url = url_data['url']
    elements = url_data['elements']
    page_title = url_data['page_title'].strip()
    domain = urlparse(url).netloc
    page_name = page_title.replace(' ', '')
    crud_operations = url_data.get('crud_operations', {})

    script = f"""// {page_title} Test Suite for {domain}
// Generated on: {url}
// Purpose: Comprehensive E2E tests including CRUD operations
// Enhanced with intelligent CRUD operation detection

const {page_name}Page = require('./{page_name}Page');

Cypress.config('defaultCommandTimeout', 10000);
Cypress.config('pageLoadTimeout', 30000);

describe('{page_title} - Enhanced Test Suite with CRUD Operations', () => {{
  const page = new {page_name}Page();

  before(() => {{
    cy.fixture('test_data.json').as('testData');
  }});

  beforeEach(() => {{
    page.visit();
    cy.window().should('have.property', 'document.readyState', 'complete');
    cy.get('body').should('be.visible');
    
    // Intercept API calls for better testing
    cy.intercept('POST', '**/api/**').as('apiPost');
    cy.intercept('GET', '**/api/**').as('apiGet');
    cy.intercept('PUT', '**/api/**').as('apiPut');
    cy.intercept('PATCH', '**/api/**').as('apiPatch');
    cy.intercept('DELETE', '**/api/**').as('apiDelete');
  }});

  describe('Smoke Tests', () => {{
    it('loads the page successfully', () => {{
      cy.url().should('eq', '{url}');
      cy.title().should('not.be.empty');
      cy.get('body').should('be.visible');
    }});
    
    it('has no console errors', () => {{
      cy.window().then((win) => {{
        cy.stub(win.console, 'error').as('consoleError');
      }});
      cy.reload();
      cy.get('@consoleError').should('not.have.been.called');
    }});
  }});
"""

    # Add CRUD operation tests
    crud_tests = generate_crud_tests(crud_operations, soup)
    script += crud_tests

    # Add API tests if network requests were detected
    if url_data.get('network_requests'):
        script += """
  describe('API Integration Tests', () => {
    it('should handle API responses correctly', () => {
      // Test API endpoints discovered during crawling
      cy.intercept('GET', '**/api/**', { fixture: 'api_response.json' }).as('apiCall');
      
      // Trigger an action that makes an API call
      cy.get('body').then(($body) => {
        if ($body.find('button, a, form').length > 0) {
          cy.get('button, a, form').first().click();
          cy.wait('@apiCall', { timeout: 10000 });
        }
      });
    });
  });
"""

    script += """
  describe('Accessibility Tests', () => {
    it('should have proper ARIA labels and roles', () => {
      cy.get('[role]').should('exist');
      cy.get('button, a, input').each(($el) => {
        cy.wrap($el).should('have.attr', 'aria-label')
          .or('have.attr', 'title')
          .or('contain.text', /\\w+/);
      });
    });
    
    it('should be keyboard navigable', () => {
      cy.get('body').tab();
      cy.focused().should('be.visible');
    });
  });

  describe('Performance Tests', () => {
    it('should load within acceptable time', () => {
      const start = Date.now();
      cy.visit('{url}');
      cy.get('body').should('be.visible').then(() => {
        const loadTime = Date.now() - start;
        expect(loadTime).to.be.lessThan(5000); // 5 seconds
      });
    });
  });
}});
"""

    return script

def generate_page_object(url_data):
    """Generate a page object class for Cypress tests with CRUD-specific methods."""
    page_name = url_data['page_title'].replace(' ', '')
    crud_operations = url_data.get('crud_operations', {})
    
    script = f"""// Page Object for {url_data['page_title']}
// Enhanced with CRUD operation methods

class {page_name}Page {{
  visit() {{
    cy.visit('{url_data['url']}');
  }}

  getElement(selector) {{
    return cy.get(selector);
  }}

  type(selector, value) {{
    this.getElement(selector).clear().type(value);
  }}

  select(selector, valueOrText) {{
    this.getElement(selector).select(valueOrText);
  }}

  check(selector) {{
    this.getElement(selector).check({{ force: true }});
  }}

  click(selector) {{
    this.getElement(selector).click();
  }}

  // CRUD-specific methods
  createRecord(formData) {{
    // Generic method to create a record
    cy.get('form, [role="form"]').first().within(() => {{
      Object.keys(formData).forEach(field => {{
        cy.get(`[name="${{field}}"], [data-testid="${{field}}"]`)
          .clear().type(formData[field]);
      }});
      cy.get('[type="submit"], button[type="submit"]').click();
    }});
  }}

  updateRecord(formData) {{
    // Generic method to update a record
    cy.get('form, [role="form"]').first().within(() => {{
      Object.keys(formData).forEach(field => {{
        cy.get(`[name="${{field}}"], [data-testid="${{field}}"]`)
          .clear().type(formData[field]);
      }});
      cy.get('[type="submit"], button[type="submit"]').click();
    }});
  }}

  deleteRecord(confirmDelete = true) {{
    // Generic method to delete a record
    cy.get('button, a').contains(/delete|remove|destroy/i).click();
    
    if (confirmDelete) {{
      cy.get('body').then(($body) => {{
        if ($body.find('[role="dialog"], .modal, .confirm').length > 0) {{
          cy.get('[role="dialog"] button, .modal button, .confirm button')
            .contains(/confirm|yes|delete|ok/i).click();
        }}
      }});
    }}
  }}

  searchRecords(searchTerm) {{
    // Generic method to search records
    cy.get('input[type="search"], input[placeholder*="search"], [data-testid*="search"]')
      .clear().type(searchTerm);
    cy.get('button[type="submit"], button').contains(/search|find/i).click();
  }}

  waitForApiResponse(alias = 'apiCall') {{
    cy.wait(`@${{alias}}`, {{ timeout: 10000 }});
  }}

  verifySuccessMessage() {{
    cy.get('body').should('contain.text', 'success')
      .or('contain.text', 'created')
      .or('contain.text', 'updated')
      .or('contain.text', 'deleted');
  }}

  verifyErrorMessage() {{
    cy.get('body').should('contain.text', 'error')
      .or('contain.text', 'failed')
      .or('contain.text', 'invalid');
  }}
}}

module.exports = {page_name}Page;
"""
    return script

def generate_fixture_data():
    """Generate enhanced JSON fixture file for test data including CRUD scenarios."""
    return {
        'users': [
            {
                'email': 'test.user@example.com',
                'password': 'TestPassword123!',
                'username': 'testuser2025',
                'firstName': 'Test',
                'lastName': 'User',
                'phone': '555-123-4567'
            },
            {
                'email': 'admin@example.com',
                'password': 'AdminPass123!',
                'username': 'admin',
                'firstName': 'Admin',
                'lastName': 'User',
                'phone': '555-987-6543'
            }
        ],
        'testData': {
            'validInput': 'Valid Test Data',
            'invalidInput': '',
            'longInput': 'A' * 255,
            'specialChars': '!@#$%^&*()',
            'numbers': '1234567890',
            'email': 'test@example.com',
            'url': 'https://example.com',
            'date': '2025-01-01'
        },
        'api_response': {
            'success': true,
            'message': 'Operation completed successfully',
            'data': {
                'id': 1,
                'name': 'Test Item',
                'created_at': '2025-01-01T00:00:00Z'
            }
        }
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/generate', methods=['POST'])
def generate_script():
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
            
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        # Use enhanced crawling with CRUD detection
        url_data = crawl_website_with_crud_detection(url)
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
        
        # Generate enhanced page object
        page_script = generate_page_object(url_data)
        page_filename = secure_filename(f"{url_data['page_title'].replace(' ', '')}Page.js")
        page_filepath = os.path.join(app.config['UPLOAD_FOLDER'], page_filename)
        
        with open(page_filepath, 'w') as f:
            f.write(page_script)
        
        # Generate enhanced fixture data
        fixture_data = generate_fixture_data()
        fixture_filename = 'test_data.json'
        fixture_filepath = os.path.join(app.config['UPLOAD_FOLDER'], fixture_filename)
        
        with open(fixture_filepath, 'w') as f:
            json.dump(fixture_data, f, indent=2)
        
        # Generate enhanced Cypress script with CRUD tests
        soup = BeautifulSoup(requests.get(url, timeout=30).text, 'html.parser')
        script = generate_enhanced_cypress_script(url_data, soup)
        
        # Save the final script
        domain = urlparse(url).netloc.replace('.', '_')
        filename = secure_filename(f"cypress_test_{domain}_enhanced.js")
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
            'crud_operations': url_data['crud_operations'],
            'network_requests_count': len(url_data.get('network_requests', [])),
            'ai_enhanced': True,
            'crud_enhanced': True
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analyze_cv', methods=['POST'])
def analyze_cv():
    """Enhanced CV analysis endpoint with interactive feedback."""
    try:
        data = request.get_json()
        cv_content = data.get('cv_content', '').strip()
        interaction_type = data.get('interaction_type', 'analyze')  # analyze, experience, skills, education, etc.
        
        if not cv_content:
            return jsonify({'error': 'CV content is required'}), 400
        
        if not app.config['OPENAI_API_KEY']:
            return jsonify({'error': 'OpenAI API key not configured'}), 500
        
        client = OpenAI(api_key=app.config['OPENAI_API_KEY'])
        
        # Different prompts based on interaction type
        prompts = {
            'analyze': f"""Analyze this CV content and provide comprehensive feedback:
            
            {cv_content}
            
            Please provide:
            1. Overall assessment of the CV
            2. Strengths and weaknesses
            3. Suggestions for improvement
            4. Missing sections or information
            5. Formatting and presentation feedback
            
            Return as JSON with keys: assessment, strengths, weaknesses, suggestions, missing_sections, formatting_feedback""",
            
            'experience': f"""Focus on the work experience section of this CV:
            
            {cv_content}
            
            Provide detailed feedback on:
            1. Quality of experience descriptions
            2. Relevance to career goals
            3. Achievement quantification
            4. Skills demonstrated
            5. Career progression
            
            Return as JSON with keys: experience_quality, relevance, achievements, skills_shown, career_progression""",
            
            'skills': f"""Analyze the skills section of this CV:
            
            {cv_content}
            
            Provide feedback on:
            1. Technical skills listed
            2. Soft skills mentioned
            3. Skill relevance to industry
            4. Missing important skills
            5. Skill presentation format
            
            Return as JSON with keys: technical_skills, soft_skills, relevance, missing_skills, presentation""",
            
            'education': f"""Review the education section of this CV:
            
            {cv_content}
            
            Analyze:
            1. Educational background relevance
            2. Certifications and courses
            3. Academic achievements
            4. Continuing education
            5. Presentation of educational info
            
            Return as JSON with keys: background_relevance, certifications, achievements, continuing_education, presentation""",
            
            'suggestions': f"""Provide specific, actionable suggestions to improve this CV:
            
            {cv_content}
            
            Give detailed recommendations for:
            1. Content improvements
            2. Structure and formatting
            3. Keywords to add
            4. Sections to enhance
            5. Industry-specific advice
            
            Return as JSON with keys: content_improvements, structure_formatting, keywords, sections_to_enhance, industry_advice"""
        }
        
        prompt = prompts.get(interaction_type, prompts['analyze'])
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            response_format={"type": "json_object"}
        )
        
        if not response.choices or not response.choices[0].message:
            return jsonify({'error': 'No response from AI'}), 500
        
        try:
            feedback = json.loads(response.choices[0].message.content)
            
            # Add interactive elements based on the feedback
            interactive_elements = []
            
            if interaction_type == 'analyze':
                interactive_elements = [
                    {'type': 'button', 'label': 'Deep Dive into Experience', 'action': 'experience'},
                    {'type': 'button', 'label': 'Analyze Skills Section', 'action': 'skills'},
                    {'type': 'button', 'label': 'Review Education', 'action': 'education'},
                    {'type': 'button', 'label': 'Get Specific Suggestions', 'action': 'suggestions'}
                ]
            elif interaction_type in ['experience', 'skills', 'education']:
                interactive_elements = [
                    {'type': 'button', 'label': 'Get Overall Analysis', 'action': 'analyze'},
                    {'type': 'button', 'label': 'Get Improvement Suggestions', 'action': 'suggestions'}
                ]
            
            return jsonify({
                'feedback': feedback,
                'interaction_type': interaction_type,
                'interactive_elements': interactive_elements,
                'success': True
            })
            
        except json.JSONDecodeError:
            return jsonify({'error': 'Failed to parse AI response'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/test_types', methods=['GET'])
def get_test_types():
    """Return enhanced test types including CRUD operations."""
    return jsonify({
        'test_types': [
            {'id': 'basic', 'name': 'Basic Page Tests', 'description': 'Tests that the page loads and basic elements are visible'},
            {'id': 'interactive', 'name': 'Interactive Element Tests', 'description': 'Tests for forms, buttons, and inputs'},
            {'id': 'crud', 'name': 'CRUD Operation Tests', 'description': 'Tests for Create, Read, Update, Delete operations'},
            {'id': 'api', 'name': 'API Integration Tests', 'description': 'Tests for API endpoints and responses'},
            {'id': 'auth', 'name': 'Authentication Tests', 'description': 'Tests for login flows'},
            {'id': 'validation', 'name': 'Validation Tests', 'description': 'Tests for form validation'},
            {'id': 'accessibility', 'name': 'Accessibility Tests', 'description': 'Tests for ARIA labels, keyboard navigation'},
            {'id': 'performance', 'name': 'Performance Tests', 'description': 'Tests for page load times and responsiveness'}
        ]
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

