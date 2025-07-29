import unittest

import ics.errors
from ics.attributes import AttributeObject

test_attributes = {
    "attr1": {
        "default": "none",
        "type": "string",
        "description": ""
    },
    "attr2": {
        "default": "false",
        "type": "boolean",
        "description": ""
    },
    "attr3": {
        "default": "",
        "type": "string",
        "description": ""
    },
    "attr4": {
        "default": [],
        "type": "list",
        "description": ""
    }
}


class TestAttributeObject(unittest.TestCase):

    def setUp(self) -> None:
        self.attribute_object = AttributeObject()
        self.attribute_object.init_attr(test_attributes)

    def test_modified_attributes(self):
        modified_attr = self.attribute_object.modified_attributes()
        self.assertEqual(modified_attr, {})
        self.attribute_object.set_attr('attr2', 'true')
        modified_attr = self.attribute_object.modified_attributes()
        correct_modified_attr = {'attr2': 'true'}
        self.assertEqual(modified_attr, correct_modified_attr)

    def test_set_attr(self):
        self.attribute_object.set_attr('attr2', 'true')
        self.assertEqual(self.attribute_object.attr_value('attr2'), 'true')
        with self.assertRaises(ics.errors.ICSError):
            self.attribute_object.set_attr('attr99', 'true')

    def test_attr_value(self):
        self.assertEqual(self.attribute_object.attr_value('attr2'), 'false')
        with self.assertRaises(ics.errors.ICSError):
            self.attribute_object.attr_value('attr99')

    def test_attr_list(self):
        test_attributes_list = [('attr1', 'none'), ('attr2', 'false'), ('attr3', ''), ('attr4', [])]
        self.assertEqual(self.attribute_object.attr_list(), test_attributes_list)
        self.attribute_object.set_attr('attr2', 'true')
        self.assertNotEqual(self.attribute_object.attr_list(), test_attributes_list)

    def test_attr_append_value(self):
        with self.assertRaises(ics.errors.ICSError):
            self.attribute_object.attr_append_value('attr1', 'value1')
        self.attribute_object.attr_append_value('attr4', 'value1')
        self.attribute_object.attr_append_value('attr4', 'value2')
        self.assertEqual(self.attribute_object.attr_value('attr4'), ['value1', 'value2'])

    def test_attr_remove_value(self):
        with self.assertRaises(ics.errors.ICSError):
            self.attribute_object.attr_remove_value('attr1', 'value1')
        self.attribute_object.attr_append_value('attr4', 'value1')
        self.attribute_object.attr_append_value('attr4', 'value2')
        self.attribute_object.attr_remove_value('attr4', 'value2')
        self.assertEqual(self.attribute_object.attr_value('attr4'), ['value1'])


if __name__ == "__main__":
    unittest.main()
