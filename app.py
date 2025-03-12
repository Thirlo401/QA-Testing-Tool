Im going to provide a python script this script crawls and then compiles a cypress script please add AI in for reasoning so that it uses intelligence to compile the scripts in a functional way that makes sense in production: from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup
import os
import re
import json
from werkzeug.utils import secure_filename
from urllib.parse import urlparse

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'generated_scripts'

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def crawl_website(url):
    """Crawl website and extract testable elements with enhanced selector detection."""
    try:
        # Add user agent to avoid being blocked
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # Raise exception for 4XX/5XX responses
        soup = BeautifulSoup(response.text, 'html.parser')
        
        elements = []
        # Find all interactive elements with expanded selector types
        interactive_selectors = [
            'input', 'button', 'a', 'form', 'select', 'textarea'
        ]
        
        # Add custom attribute selectors for dynamic elements
        attr_selectors = [
            '[role="button"]', '[role="checkbox"]', '[role="radio"]', '[role="tab"]',
            '[role="menuitem"]', '[role="switch"]', '[data-testid]', '[data-cy]',
            '[data-test]', '[data-automation-id]', '[aria-label]'
        ]
        
        # Extract interactive elements
        for selector in interactive_selectors:
            for element in soup.find_all(selector):
                elem_data = extract_element_data(element)
                elements.append(elem_data)
        
        # Extract elements with special attributes
        for selector in attr_selectors:
            for element in soup.select(selector):
                if element.name not in interactive_selectors:
                    elem_data = extract_element_data(element)
                    elements.append(elem_data)
        
        # Add page metadata
        page_title = soup.title.string if soup.title else "Unknown Page"
        
        return {
            'elements': elements,
            'page_title': page_title,
            'url': url
        }
    except Exception as e:
        print(f"Error crawling website: {str(e)}")
        return {
            'elements': [],
            'page_title': "Error Page",
            'url': url,
            'error': str(e)
        }

def extract_element_data(element):
    """Extract relevant data from an HTML element."""
    # Convert class list to string
    class_list = element.get('class', [])
    class_str = ' '.join(class_list) if isinstance(class_list, list) else class_list
    
    # Get visible text content
    text_content = ''
    if element.name not in ['input', 'textarea', 'select']:
        text_content = element.get_text().strip()
        # Limit text content length and clean it up
        if len(text_content) > 50:
            text_content = text_content[:50].strip() + "..."
        text_content = re.sub(r'\s+', ' ', text_content)
    
    # Extract element attributes
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
        'visible': True,  # Assume element is visible for now
        'xpath': get_xpath(element),
        'required': element.has_attr('required')
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

def get_best_selector(element):
    """Determine the best selector strategy for an element."""
    # Prioritize testing-specific attributes
    if element['data-testid']:
        return f"[data-testid='{element['data-testid']}']"
    elif element['data-cy']:
        return f"[data-cy='{element['data-cy']}']"
    elif element['data-test']:
        return f"[data-test='{element['data-test']}']"
    elif element['data-automation-id']:
        return f"[data-automation-id='{element['data-automation-id']}']"
    elif element['id']:
        return f"#{element['id']}"
    elif element['name']:
        return f"[name='{element['name']}']"
    elif element['aria-label']:
        return f"[aria-label='{element['aria-label']}']"
    elif element['text_content'] and element['tag'] not in ['input', 'textarea', 'select']:
        # Handle text content with quotes
        text = element['text_content'].replace("'", "\\'")
        return f":contains('{text}')"
    elif element['placeholder']:
        return f"[placeholder='{element['placeholder']}']"
    elif element['class'] and not ' ' in element['class']:
        # Only use class if it's a single class, multiple classes can be brittle
        return f".{element['class']}"
    elif element['type']:
        return f"{element['tag']}[type='{element['type']}']"
    else:
        # If all else fails, use xpath as fallback
        return element['xpath']

def generate_realistic_input_value(element):
    """Generate realistic test data based on input type."""
    input_type = element.get('type', '').lower()
    name = element.get('name', '').lower()
    placeholder = element.get('placeholder', '').lower()
    
    # Check for common patterns in name/placeholder
    if any(term in name or term in placeholder for term in ['email', 'e-mail']):
        return 'test.user@example.com'
    elif any(term in name or term in placeholder for term in ['password', 'pwd']):
        return 'TestPassword123!'
    elif any(term in name or term in placeholder for term in ['username', 'user', 'login']):
        return 'testuser2025'
    elif any(term in name or term in placeholder for term in ['phone', 'mobile', 'tel']):
        return '555-123-4567'
    elif any(term in name or term in placeholder for term in ['zip', 'postal']):
        return '10001'
    elif any(term in name or term in placeholder for term in ['address']):
        return '123 Test Street'
    elif any(term in name or term in placeholder for term in ['city']):
        return 'New York'
    elif any(term in name or term in placeholder for term in ['state']):
        return 'NY'
    elif any(term in name or term in placeholder for term in ['country']):
        return 'United States'
    
    # Then check by input type
    if input_type == 'email':
        return 'test.user@example.com'
    elif input_type == 'password':
        return 'TestPassword123!'
    elif input_type == 'search':
        return 'test query'
    elif input_type == 'tel':
        return '555-123-4567'
    elif input_type == 'number':
        return '42'
    elif input_type == 'date':
        return '2025-03-15'
    elif input_type == 'url':
        return 'https://example.com'
    else:
        return 'Test Input Value'

def generate_cypress_script(url_data):
    """Generate enhanced Cypress test script with better assertions and interactions."""
    url = url_data['url']
    elements = url_data['elements']
    page_title = url_data['page_title']
    
    # Extract domain for the describe block
    domain = urlparse(url).netloc
    
    script = f"""// Cypress test suite for {page_title} on {domain}
// Generated on {url}
// This script includes realistic test interactions and dynamic waiting

describe('{page_title} - Automated Tests', () => {{
  beforeEach(() => {{
    // Visit the target website with configured timeout
    cy.visit('{url}', {{ timeout: 30000 }})
    
    // Wait for page to be fully loaded
    cy.window().should('have.property', 'document')
      .then(doc => {{
        return new Cypress.Promise(resolve => {{
          if (doc.readyState === 'complete') {{
            resolve()
          }} else {{
            const listener = () => {{
              doc.removeEventListener('load', listener)
              resolve()
            }}
            doc.addEventListener('load', listener)
          }}
        }})
      }})
    
    // Intercept and wait for network requests to complete
    cy.intercept('**').as('networkRequests')
    cy.wait('@networkRequests', {{ timeout: 10000 }}).its('response.statusCode').should('be.lt', 400)
  }})

  // Basic page validation test
  it('should load the page successfully', () => {{
    // Check URL and page title
    cy.url().should('include', '{domain}')
    cy.title().should('include', '{page_title}')
    
    // Verify the page loaded without errors
    cy.document().should('have.property', 'readyState', 'complete')
    cy.get('body').should('be.visible')
  }})

"""
    
    # Group elements by type for better test organization
    forms = [e for e in elements if e['tag'] == 'form']
    inputs = [e for e in elements if e['tag'] == 'input' and e not in forms]
    buttons = [e for e in elements if e['tag'] == 'button' or (e['role'] == 'button' and e['tag'] != 'a')]
    links = [e for e in elements if e['tag'] == 'a' and e['role'] != 'button']
    selects = [e for e in elements if e['tag'] == 'select']
    textareas = [e for e in elements if e['tag'] == 'textarea']
    
    # Create form tests
    if forms:
        script += "\n  // Form Tests\n"
        for idx, form in enumerate(forms):
            form_id = form['id'] or f"form-{idx+1}"
            selector = get_best_selector(form)
            
            # Find form inputs
            form_fields = []
            for field_type in ['input', 'select', 'textarea']:
                for field in elements:
                    if field['tag'] == field_type:
                        # Simple check if field might be in this form
                        field_selector = get_best_selector(field)
                        if not field_selector.startswith('//'): # Skip XPath selectors for this check
                            form_fields.append(field)
            
            script += f"""
  it('should interact with form {form_id}', () => {{
    cy.get('{selector}').should('exist').within(() => {{
"""
            
            # Add specific input field tests within the form context
            for field in form_fields[:3]:  # Limit to first 3 fields to avoid overly complex tests
                field_selector = get_best_selector(field)
                
                if field['tag'] == 'input':
                    input_type = field['type'].lower() if field['type'] else 'text'
                    
                    if input_type in ['checkbox', 'radio']:
                        script += f"""
      // Interact with {input_type} field
      cy.get('{field_selector}').should('exist')
        .check().should('be.checked')
"""
                    elif input_type == 'submit':
                        # Just verify submit button exists, don't click it yet
                        script += f"""
      // Verify submit button exists
      cy.get('{field_selector}').should('exist').should('be.visible')
"""
                    else:
                        # Generate realistic test value based on field type/name
                        test_value = generate_realistic_input_value(field)
                        script += f"""
      // Fill in {input_type} field
      cy.get('{field_selector}').should('exist').should('be.visible')
        .clear().type('{test_value}', {{ delay: 50 }})
        .should('have.value', '{test_value}')
"""
                
                elif field['tag'] == 'select':
                    script += f"""
      // Select dropdown option
      cy.get('{field_selector}').should('exist')
        .select(1) // Select second option
        .should('not.have.value', '')
"""
                
                elif field['tag'] == 'textarea':
                    script += f"""
      // Fill in textarea
      cy.get('{field_selector}').should('exist')
        .clear().type('This is a test comment with realistic content for testing purposes.', {{ delay: 50 }})
        .should('contain.value', 'test comment')
"""
            
            script += f"""
      // Form submission test - prevented with Cypress.stop() to avoid actual form submission
      cy.on('form:submit', (e) => {{
        e.preventDefault()
        Cypress.log({{ name: 'Form Submission', message: 'Prevented form submission during test' }})
      }})
    }})
  }})
"""
    
    # Create input field tests
    if inputs:
        script += "\n  // Input Field Tests\n"
        for idx, input_elem in enumerate(inputs[:5]):  # Limit to first 5 inputs
            input_type = input_elem['type'].lower() if input_elem['type'] else 'text'
            selector = get_best_selector(input_elem)
            
            if input_type == 'checkbox':
                script += f"""
  it('should toggle checkbox {idx+1}', () => {{
    cy.get('{selector}').should('exist').then($el => {{
      if ($el.is(':visible')) {{
        cy.wrap($el)
          .check()
          .should('be.checked')
          .uncheck()
          .should('not.be.checked')
      }} else {{
        cy.log('Checkbox not visible or accessible')
      }}
    }})
  }})
"""
            elif input_type == 'radio':
                script += f"""
  it('should select radio button {idx+1}', () => {{
    cy.get('{selector}').should('exist').then($el => {{
      if ($el.is(':visible')) {{
        cy.wrap($el)
          .check()
          .should('be.checked')
      }} else {{
        cy.log('Radio button not visible or accessible')
      }}
    }})
  }})
"""
            elif input_type not in ['submit', 'button', 'hidden', 'file']:
                test_value = generate_realistic_input_value(input_elem)
                script += f"""
  it('should fill input field {idx+1} ({input_type})', () => {{
    cy.get('{selector}').should('exist').then($el => {{
      if ($el.is(':visible')) {{
        cy.wrap($el)
          .clear()
          .type('{test_value}', {{ delay: 50 }})
          .should('have.value', '{test_value}')
      }} else {{
        cy.log('Input field not visible or accessible')
      }}
    }})
  }})
"""
    
    # Create button tests
    if buttons:
        script += "\n  // Button Tests\n"
        for idx, button in enumerate(buttons[:5]):  # Limit to first 5 buttons
            selector = get_best_selector(button)
            button_text = button['text_content'] or f"Button {idx+1}"
            
            script += f"""
  it('should verify button: {button_text}', () => {{
    cy.get('{selector}').should('exist').then($btn => {{
      if ($btn.is(':visible') && $btn.is(':enabled')) {{
        // Log button details but don't click to avoid navigation
        cy.log(`Button found: ${button_text}`)
        cy.wrap($btn).should('be.visible')
      }} else {{
        cy.log('Button not visible, enabled, or accessible')
      }}
    }})
  }})
"""
    
    # Create link tests
    if links:
        script += "\n  // Link Tests\n"
        for idx, link in enumerate(links[:5]):  # Limit to first 5 links
            selector = get_best_selector(link)
            link_text = link['text_content'] or f"Link {idx+1}"
            
            script += f"""
  it('should verify link: {link_text}', () => {{
    cy.get('{selector}').should('exist').then($link => {{
      if ($link.is(':visible')) {{
        cy.wrap($link)
          .should('have.attr', 'href')
          .and('not.be.empty')
        
       
        
        // Don't actually click links to avoid navigation
      }} else {{
        cy.log('Link not visible or accessible')
      }}
    }})
  }})
"""
    
    # Create select dropdown tests
    if selects:
        script += "\n  // Dropdown Tests\n"
        for idx, select in enumerate(selects[:3]):  # Limit to first 3 dropdowns
            selector = get_best_selector(select)
            
            script += f"""
  it('should interact with dropdown {idx+1}', () => {{
    cy.get('{selector}').should('exist').then($select => {{
      if ($select.is(':visible')) {{
        cy.wrap($select)
          .find('option')
          .should('have.length.at.least', 1)
          .then($options => {{
            if ($options.length > 1) {{
              cy.wrap($select).select(1) // Select second option if available
            }} else {{
              cy.log('Dropdown has too few options for testing')
            }}
          }})
      }} else {{
        cy.log('Dropdown not visible or accessible')
      }}
    }})
  }})
"""
    
    # Create textarea tests
    if textareas:
        script += "\n  // Textarea Tests\n"
        for idx, textarea in enumerate(textareas[:3]):  # Limit to first 3 textareas
            selector = get_best_selector(textarea)
            
            script += f"""
  it('should fill textarea {idx+1}', () => {{
    cy.get('{selector}').should('exist').then($textarea => {{
      if ($textarea.is(':visible')) {{
        cy.wrap($textarea)
          .clear()
          .type('This is a sample text for testing the textarea functionality. It has multiple sentences to simulate realistic user input.', {{ delay: 20 }})
          .should('contain.value', 'sample text')
      }} else {{
        cy.log('Textarea not visible or accessible')
      }}
    }})
  }})
"""
    
    # Add a visual test if needed
    script += """
  // Visual regression test (optional) 
  it('should match visual snapshot', () => {
    // Uncomment this line if using cypress-image-snapshot plugin
    // cy.screenshot('full-page')
  })

  // Add custom commands for reusable interactions
  Cypress.Commands.add('fillForm', (selectors) => {
    Object.entries(selectors).forEach(([selector, value]) => {
      cy.get(selector).then($el => {
        if ($el.is(':visible')) {
          cy.wrap($el).clear().type(value)
        }
      })
    })
  })

  Cypress.Commands.add('safeClick', (selector) => {
    cy.get(selector).then($el => {
      if ($el.is(':visible') && $el.is(':enabled')) {
        cy.wrap($el).click()
      } else {
        cy.log(`Element ${selector} not clickable`)
      }
    })
  })
})
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
            
        # Validate URL format
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        # Crawl the website and get elements
        url_data = crawl_website(url)
        
        if not url_data['elements']:
            return jsonify({
                'error': 'No testable elements found', 
                'details': url_data.get('error', 'The page might be using client-side rendering or blocking crawlers')
            }), 400

        # Generate the Cypress script
        script = generate_cypress_script(url_data)
        
        # Create sanitized filename
        domain = urlparse(url).netloc.replace('.', '_')
        filename = secure_filename(f"cypress_test_{domain}.js")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Save the script to a file
        with open(filepath, 'w') as f:
            f.write(script)

        # Return the result
        return jsonify({
            'script': script,
            'filename': filename,
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
            {'id': 'api', 'name': 'API Tests', 'description': 'Tests for API endpoints (requires URL patterns)'},
            {'id': 'performance', 'name': 'Performance Tests', 'description': 'Basic performance metrics for the page'}
        ]
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
