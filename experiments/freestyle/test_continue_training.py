import unittest
from .continue_training import loss_only_evaluation


class TrainingEvaluationTests(unittest.TestCase):
    def test_loss_tensor_is_unchanged_and_training_and_generation_outputs_are_preserved(self):
        class Model:
            training = False
            result = {'loss': object(), 'logits': object()}
            def forward(self, labels=None):
                return self.result
        model = Model()
        loss_only_evaluation(model)
        result = model.forward(labels=[1, 2])
        self.assertEqual(set(result), {'loss'})
        self.assertIs(result['loss'], model.result['loss'])
        model.training = True
        self.assertIs(model.forward(labels=[1, 2]), model.result)
        model.training = False
        self.assertIs(model.forward(), model.result)
