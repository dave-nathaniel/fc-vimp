'''
	A collection of functions that contain the logic of how products should be converted.
	
	TODO: Document the rules.
	
	1. Always return "quantity_received"
'''


def chicken_conversion(*args, **kwargs):
	"""
		Converts KG chicken to pieces.
		Inputs:
			- birds_per_bag
			- weight_of_bird
			- number_of_bags
			
		[
		  {
		    "name": "birds_per_bag",
		    "type": "number",
		    "properties": {
		      "placeholder": "The number of birds in a bag.",
		      "min": 1,
		      "required": true
		    }
		  },
		  {
		    "name": "number_of_bags",
		    "type": "number",
		    "properties": {
		      "placeholder": "The number bags supplied.",
		      "min": 1,
		      "required": true
		    }
		  },
		  {
		    "name": "weight_of_bird",
		    "type": "select",
		    "options": [
		      {
		        "name": "1.2 kg",
		        "value": "1.2"
		      },
		      {
		        "name": "1.3 kg",
		        "value": "1.3"
		      },
		      {
		        "name": "1.4 kg",
		        "value": "1.4"
		      },
		      {
		        "name": "1.5 kg",
		        "value": "1.5"
		      },
		      {
		        "name": "1.6 kg",
		        "value": "1.6"
		      }
		    ],
		    "properties": {
		      "placeholder": "The weight of each bird in a bag.",
		      "required": true
		    }
		  }
		]
	"""
	inputs = kwargs.get('input_fields')
	
	number_of_bag = float(inputs.get('number_of_bags'))
	birds_per_bag = float(inputs.get('birds_per_bag'))
	weight_of_bird = float(inputs.get('weight_of_bird'))
	
	# Convert KG to pounds for consistency with other conversions
	kg_to_pcs = 0
	# Chicken pieces conversion factor
	if weight_of_bird >= 1.0 and weight_of_bird < 1.3:
		kg_to_pcs = 6
	elif weight_of_bird >= 1.3 and weight_of_bird < 1.5:
		kg_to_pcs = 9
	elif weight_of_bird >= 1.5 and weight_of_bird < 1.9:
		kg_to_pcs = 12
	
	return {
		"quantity_received": round(float(number_of_bag * birds_per_bag * weight_of_bird), 2),
		"total_pieces_received": number_of_bag * birds_per_bag * kg_to_pcs,
		"total_weight_received": number_of_bag * birds_per_bag * weight_of_bird
	}


def nbc_products_volume_conversion(*args, **kwargs):
	'''
		Volume of NBC product received e.g 35cl, 50CL, 1Litre.
		Number of NBC products in a pack
		Number of packs received
		Upon inputting these required details, The system should do the following :
			Calculate the extended volume received. This is realized with the formular:
				Volume of Product received × Number in a pack × Number of packs received
		
		[
			{
				"name":"number_of_packs",
				"type":"number",
				"properties":{
					"placeholder":"The total number of packs received.",
					"min":1,
					"required":true
				}
			},
			{
				"name":"number_per_pack",
				"type":"number",
				"properties":{
				"placeholder":"The number products in a complete pack.",
				"min":1,
				"required":true
			}},
			{
				"name":"product_volume",
				"type":"select",
				"properties":{
					"placeholder":"The volume of this product, as stated on the product's container.",
					"required":true,
					"options":[
						{"name":"35cl","value":"35"},
						{"name":"50cl","value":"50"},
						{"name":"1L","value":"100"},
					]
			}}
		]
	'''
	inputs = kwargs.get('input_fields')
	
	number_of_packs_received = float(inputs.get('number_of_packs_received') or 0.00)
	number_per_pack = float(inputs.get('number_per_pack') or 0.00)
	product_volume = (float(inputs.get('product_volume') or 0.00) / 100.00) # Given that 1L = 100cl, we want to get the value in Litres
	
	extended_volume_received = product_volume * number_per_pack * number_of_packs_received
	
	return {
		"quantity_received": number_of_packs_received * number_per_pack,
		"extended_volume_received": extended_volume_received
	}
	