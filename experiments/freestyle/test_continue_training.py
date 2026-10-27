import unittest
from .continue_training import loss_only_evaluation, configure_loss_weighting


class TrainingEvaluationTests(unittest.TestCase):
    def test_short_completion_and_long_program_have_equal_example_gradient(self):
        import tempfile
        import torch
        from transformers import Trainer, TrainingArguments
        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__();self.weight=torch.nn.Parameter(torch.tensor(0.))
            def forward(self,input_ids,labels=None,num_items_in_batch=None,**kwargs):
                errors=(self.weight-input_ids.float()).square()
                return {'loss':errors.sum()/(num_items_in_batch if num_items_in_batch is not None else errors.numel())}
        with tempfile.TemporaryDirectory() as directory:
            model=Model();trainer=Trainer(model=model,args=TrainingArguments(
                output_dir=directory,use_cpu=True,report_to='none'))
            trainer.model_accepts_loss_kwargs=True
            def loss(count,target):
                return trainer.compute_loss(model,{'input_ids':torch.full((1,count),target),
                    'labels':torch.zeros((1,count),dtype=torch.long)},num_items_in_batch=297)
            weighted=loss(3,1)+loss(294,3);weighted.backward()
            self.assertAlmostEqual(model.weight.grad.item(),-1770/297,places=5)
            model.zero_grad()
            configure_loss_weighting(trainer,{'loss_weighting':'example','per_device_train_batch_size':1})
            balanced=(loss(3,1)+loss(294,3))/2;balanced.backward()
            self.assertAlmostEqual(balanced.item(),5.)
            self.assertAlmostEqual(model.weight.grad.item(),-4.)

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
