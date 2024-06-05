def chicken_conversion(*args, **kwargs):
	"""
		Converts KG chicken to pieces.
		Inputs:
			- birds_per_bag
			- weight_of_bird
			- number_of_bags
	"""
	inputs = kwargs.get('input_fields')
	
	number_of_bag = float(inputs.get('number_of_bags'))
	birds_per_bag = float(inputs.get('birds_per_bag'))
	weight_of_bird = float(inputs.get('weight_of_bird'))
	
	# Chicken pieces conversion factor
	kg_to_pcs = 0
	if weight_of_bird >= 1.0 and weight_of_bird < 1.3:
		kg_to_pcs = 6
	elif weight_of_bird >= 1.3 and weight_of_bird < 1.5:
		kg_to_pcs = 9
	elif weight_of_bird >= 1.5 and weight_of_bird < 1.9:
		kg_to_pcs = 12
		
	return {
		"quantity_received":  round(float(number_of_bag * birds_per_bag * weight_of_bird), 2),
		"total_pieces_received": number_of_bag * birds_per_bag * kg_to_pcs,
		"total_weight_received": number_of_bag * birds_per_bag * weight_of_bird
	}